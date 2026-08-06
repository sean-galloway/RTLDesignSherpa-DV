# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Per-bank DRAM state machine + JEDEC timing violation checker (issue #16).

The :class:`DramStateModel` tracks per-bank state (idle / active / etc.)
and the cycle at which each transition happened. The :class:`DFISlavePHY`
calls into it for every command the MC issues on the wire; the model
reports timing violations via :class:`ViolationPolicy` — by default,
critical JEDEC sequencing rules halt sim, windowed/average rules warn,
init-sequence specifics are ignored.

Scope: the "hard" checks are fully wired (5 bank-state transitions +
8 timing parameters), tFAW uses a 4-deep ACT-history window, and
tREFI-overdue windowing enforces the JEDEC postpone limit (up to 8
refreshes may be postponed, so the maximum REF-to-REF interval is
9 x tREFI; exceeding it reports a soft "tREFI" violation once per
missed window). Wire-level read-data and write-data servicing lives
in :mod:`dfi_slave_phy`, not here.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, FrozenSet, List, Optional, Tuple

from .jedec_timings import JedecTimings

# ----------------------------------------------------------------------
# Address mapping
# ----------------------------------------------------------------------


# Field names recognized in the mapping string. Order matters: MSB→LSB
# in the resulting flat index, per the mapping string the user supplies.
_ADDR_FIELDS = ("rank", "bank", "row", "col")


def _is_pow2(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def _bit_width(n: int) -> int:
    """Number of bits needed to address ``n`` distinct values (n=1 → 0)."""
    if n <= 1:
        return 0
    return (n - 1).bit_length()


@dataclass(frozen=True)
class AddressMapping:
    """Configurable flat ↔ (rank, bank, row, col) decoder.

    Models DRAMsim3's late-binding address decode (configuration.cc
    SetAddressMapping). The mapping string is a pipe-separated MSB→LSB
    field order, e.g. ``"row|bank|col"`` for the conventional
    row-buffer-friendly layout, or ``"row|col|bank"`` to push banks
    into the LSBs.

    Geometry args set the per-field widths; the mapping just dictates
    the slice order. All counts must be powers of 2.

    The decoder works in **column units** (not bytes). The caller is
    responsible for the column-to-byte stride (``col * BL * bus_width/8``)
    if a byte offset is needed.
    """

    num_ranks: int
    num_banks: int
    num_rows: int
    num_cols: int
    mapping: str = "row|bank|col"

    # Computed at __post_init__ — kept private to the frozen dataclass.
    _widths: Dict[str, int] = field(default_factory=dict, repr=False, compare=False)
    _shifts: Dict[str, int] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name, n in (
            ("num_ranks", self.num_ranks),
            ("num_banks", self.num_banks),
            ("num_rows", self.num_rows),
            ("num_cols", self.num_cols),
        ):
            if not _is_pow2(n):
                raise ValueError(f"{name}={n} must be a power of 2")

        fields = [f.strip() for f in self.mapping.split("|") if f.strip()]
        for f in fields:
            if f not in _ADDR_FIELDS:
                raise ValueError(
                    f"unknown field {f!r} in mapping {self.mapping!r}; "
                    f"expected one of {_ADDR_FIELDS}"
                )
        if len(set(fields)) != len(fields):
            raise ValueError(f"duplicate field in mapping {self.mapping!r}")

        # col is always required; bank/row required when their count > 1.
        if "col" not in fields:
            raise ValueError(f"mapping {self.mapping!r} missing 'col' field")
        if self.num_banks > 1 and "bank" not in fields:
            raise ValueError(f"mapping {self.mapping!r} missing 'bank' field")
        if self.num_rows > 1 and "row" not in fields:
            raise ValueError(f"mapping {self.mapping!r} missing 'row' field")
        if self.num_ranks > 1 and "rank" not in fields:
            raise ValueError(
                f"mapping {self.mapping!r} missing 'rank' field "
                f"(num_ranks={self.num_ranks})"
            )

        widths = {
            "rank": _bit_width(self.num_ranks),
            "bank": _bit_width(self.num_banks),
            "row": _bit_width(self.num_rows),
            "col": _bit_width(self.num_cols),
        }
        # Walk MSB→LSB to assign shifts: rightmost field has shift 0.
        shifts: Dict[str, int] = {f: 0 for f in _ADDR_FIELDS}
        running = 0
        for f in reversed(fields):
            shifts[f] = running
            running += widths[f]

        # Dataclass is frozen → bypass __setattr__ for the cached dicts.
        object.__setattr__(self, "_widths", widths)
        object.__setattr__(self, "_shifts", shifts)

    @property
    def total_size(self) -> int:
        """Number of distinct flat addresses (column units)."""
        return self.num_ranks * self.num_banks * self.num_rows * self.num_cols

    def tuple_to_flat(self, rank: int, bank: int, row: int, col: int) -> int:
        """Pack ``(rank, bank, row, col)`` into a flat index."""
        for name, val, limit in (
            ("rank", rank, self.num_ranks),
            ("bank", bank, self.num_banks),
            ("row", row, self.num_rows),
            ("col", col, self.num_cols),
        ):
            if not (0 <= val < limit):
                raise ValueError(
                    f"{name}={val} out of range [0, {limit})"
                )
        return (
            (rank << self._shifts["rank"])
            | (bank << self._shifts["bank"])
            | (row << self._shifts["row"])
            | (col << self._shifts["col"])
        )

    def flat_to_tuple(self, flat: int) -> Tuple[int, int, int, int]:
        """Unpack a flat index to ``(rank, bank, row, col)``."""
        def _extract(name: str, limit: int) -> int:
            width = self._widths[name]
            if width == 0:
                return 0
            mask = (1 << width) - 1
            return (flat >> self._shifts[name]) & mask
        return (
            _extract("rank", self.num_ranks),
            _extract("bank", self.num_banks),
            _extract("row", self.num_rows),
            _extract("col", self.num_cols),
        )

# ----------------------------------------------------------------------
# Violation policy
# ----------------------------------------------------------------------


class ViolationCategory(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    IGNORE = "ignore"


# Default category for each named violation (see README.md). Override
# at construction time via ``ViolationPolicy(hard=..., soft=..., ignore=...)``.
_DEFAULT_HARD: FrozenSet[str] = frozenset({
    # Bank-state transitions
    "no_act_before_rd",
    "no_act_before_wr",
    "act_on_active_bank",
    "ref_with_open_row",
    "cmd_during_refresh",
    # Timing parameters
    "tRCD",
    "tRP",
    "tRAS_min",
    "tRC",
    "tWR",
    "tWTR",
    "tRTP",
    "tRRD",
})
_DEFAULT_SOFT: FrozenSet[str] = frozenset({
    "tFAW",
    "tREFI",
    "tRFC",        # softer because refresh model is approximate
    "CL_mismatch",
    "CWL_mismatch",
})
_DEFAULT_IGNORE: FrozenSet[str] = frozenset({
    "init_sequence",
    "zq_calibration",
    "voltage_temp",
})


class ViolationPolicy:
    """Configurable per-violation behavior.

    Defaults follow the split in the issue:
      - hard:  JEDEC-critical sequencing + per-bank timings → ``assert False``
      - soft:  windowed/average → log warning, count, continue
      - ignore: init / calibration / voltage-temp specifics → silent

    Any violation name not in any of the three sets defaults to ``SOFT``
    so future spec additions don't silently crash an existing simulation.
    """

    def __init__(
        self,
        *,
        hard: Optional[FrozenSet[str]] = None,
        soft: Optional[FrozenSet[str]] = None,
        ignore: Optional[FrozenSet[str]] = None,
    ):
        self.hard = hard if hard is not None else _DEFAULT_HARD
        self.soft = soft if soft is not None else _DEFAULT_SOFT
        self.ignore = ignore if ignore is not None else _DEFAULT_IGNORE
        self._soft_counts: dict[str, int] = {}

    def category_of(self, name: str) -> ViolationCategory:
        if name in self.hard:
            return ViolationCategory.HARD
        if name in self.ignore:
            return ViolationCategory.IGNORE
        # Default: SOFT (includes anything in self.soft plus unknowns)
        return ViolationCategory.SOFT

    def report(
        self,
        name: str,
        context: str,
        log: Optional[logging.Logger] = None,
    ) -> None:
        """Report a violation; raise / log per the configured category."""
        cat = self.category_of(name)
        if cat == ViolationCategory.IGNORE:
            return
        msg = f"DRAM timing violation [{name}]: {context}"
        if cat == ViolationCategory.HARD:
            raise AssertionError(msg)
        # SOFT
        self._soft_counts[name] = self._soft_counts.get(name, 0) + 1
        if log is not None:
            log.warning(msg)

    @property
    def soft_violation_counts(self) -> dict[str, int]:
        return dict(self._soft_counts)


# ----------------------------------------------------------------------
# Per-bank state
# ----------------------------------------------------------------------


class BankState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    REFRESHING = "refreshing"


@dataclass
class Bank:
    state: BankState = BankState.IDLE
    row: Optional[int] = None

    # Cycle counters for timing checks. -1 means "never happened yet".
    last_act_cycle: int = -1
    last_pre_cycle: int = -1
    last_rd_cycle: int = -1
    last_wr_cycle: int = -1
    last_wr_data_cycle: int = -1   # last data beat of the most recent WR burst
    last_rd_data_cycle: int = -1
    last_ref_end_cycle: int = -1


# ----------------------------------------------------------------------
# DRAM state model
# ----------------------------------------------------------------------


class DramStateModel:
    """Per-bank state machine + JEDEC timing-violation checker.

    The :class:`DFISlavePHY` calls into ``on_activate`` / ``on_read`` /
    ``on_write`` / ``on_precharge`` / ``on_refresh`` every cycle in which
    those commands appear on the wire. Refresh state is approximate —
    `cmd_during_refresh` covers the common case but the model doesn't
    yet track tRFC precisely.

    Cycle accounting: the model keeps its own ``cycle`` counter that the
    slave advances with ``tick()`` per DFI clock edge. Counters use
    inclusive comparisons (``elapsed = cycle - last_X``) so the spec's
    "ACT-to-RD must be at least tRCD cycles" reads naturally as
    ``elapsed >= tRCD_cycles``.
    """

    def __init__(
        self,
        *,
        timings: JedecTimings,
        num_banks: int,
        policy: Optional[ViolationPolicy] = None,
        log: Optional[logging.Logger] = None,
    ):
        if num_banks <= 0:
            raise ValueError(f"num_banks must be positive, got {num_banks}")
        self.timings = timings
        self.banks: List[Bank] = [Bank() for _ in range(num_banks)]
        self.policy = policy if policy is not None else ViolationPolicy()
        self.log = log
        self.cycle = 0

        # tFAW windowing: ring of the last 4 ACT cycles
        self._act_history: Deque[int] = deque(maxlen=4)

        # Last issued ACT to any bank — for tRRD
        self._last_act_any_bank: int = -1

        # Refresh tracking — last broadcast REF cycle and end-of-tRFC
        self._last_ref_cycle: int = -1
        self._ref_end_cycle: int = -1

        # tREFI windowing (JEDEC postpone limit): up to 8 refreshes may
        # be postponed, so the max legal REF-to-REF gap is 9 x tREFI.
        # Armed lazily at the first command (traffic implies the DRAM
        # is out of init and needs refresh maintenance); -1 = unarmed.
        self._refi_deadline_cycle: int = -1

    # ----- Time advance -----

    def tick(self) -> None:
        """Advance one DFI clock cycle. Call once per DFI clock edge
        (the slave's sampling loop calls it on each falling edge)."""
        self.cycle += 1
        # Walk banks out of REFRESHING once tRFC elapsed
        if (
            self._ref_end_cycle >= 0
            and self.cycle >= self._ref_end_cycle
        ):
            for b in self.banks:
                if b.state == BankState.REFRESHING:
                    b.state = BankState.IDLE
                    b.row = None
                    b.last_ref_end_cycle = self.cycle
        # tREFI window: once armed, a REF must land within 9 x tREFI
        # (8-postpone limit). Report once per missed window, then
        # re-arm so a stalled refresher logs one violation per window
        # rather than one per cycle.
        if (
            self._refi_deadline_cycle >= 0
            and self.cycle > self._refi_deadline_cycle
        ):
            self.policy.report(
                "tREFI",
                f"no REF for > 9 x tREFI "
                f"({9 * self.timings.tREFI_cycles} cycles) — refresh "
                f"overdue @ cycle {self.cycle} (last REF cycle "
                f"{self._last_ref_cycle})",
                self.log,
            )
            self._refi_deadline_cycle = (
                self.cycle + 9 * self.timings.tREFI_cycles
            )

    def _arm_refi_window(self) -> None:
        """Start the tREFI window at the first observed command."""
        if self._refi_deadline_cycle < 0:
            self._refi_deadline_cycle = (
                self.cycle + 9 * self.timings.tREFI_cycles
            )

    # ----- Command handlers -----

    def on_activate(self, bank_idx: int, row: int) -> None:
        """Process an ACT command."""
        self._arm_refi_window()
        self._check_not_refreshing("act")
        b = self._bank(bank_idx)
        if b.state == BankState.ACTIVE:
            self.policy.report(
                "act_on_active_bank",
                f"bank={bank_idx} already ACTIVE with row=0x{b.row:x}, "
                f"got new ACT row=0x{row:x} @ cycle {self.cycle}",
                self.log,
            )
            return
        # tRP: must wait after last PRE before ACT on same bank
        if b.last_pre_cycle >= 0:
            elapsed = self.cycle - b.last_pre_cycle
            if elapsed < self.timings.tRP_cycles:
                self.policy.report(
                    "tRP",
                    f"bank={bank_idx} ACT only {elapsed} cycles after PRE "
                    f"(needs {self.timings.tRP_cycles})",
                    self.log,
                )
        # tRC: ACT-to-ACT same bank
        if b.last_act_cycle >= 0:
            elapsed = self.cycle - b.last_act_cycle
            if elapsed < self.timings.tRC_cycles:
                self.policy.report(
                    "tRC",
                    f"bank={bank_idx} ACT-to-ACT only {elapsed} cycles "
                    f"(needs {self.timings.tRC_cycles})",
                    self.log,
                )
        # tRRD: ACT-to-ACT any-bank
        if self._last_act_any_bank >= 0:
            elapsed = self.cycle - self._last_act_any_bank
            if elapsed < self.timings.tRRD_cycles:
                self.policy.report(
                    "tRRD",
                    f"ACT bank={bank_idx} only {elapsed} cycles after "
                    f"last ACT (needs {self.timings.tRRD_cycles})",
                    self.log,
                )
        # tFAW: 4 ACTs must fit in tFAW cycles
        if len(self._act_history) == 4:
            window = self.cycle - self._act_history[0]
            if window < self.timings.tFAW_cycles:
                self.policy.report(
                    "tFAW",
                    f"5th ACT within {window} cycle window "
                    f"(tFAW={self.timings.tFAW_cycles})",
                    self.log,
                )

        b.state = BankState.ACTIVE
        b.row = row
        b.last_act_cycle = self.cycle
        self._last_act_any_bank = self.cycle
        self._act_history.append(self.cycle)

    def on_read(self, bank_idx: int) -> None:
        """Process a RD command."""
        self._arm_refi_window()
        self._check_not_refreshing("rd")
        b = self._bank(bank_idx)
        if b.state != BankState.ACTIVE:
            self.policy.report(
                "no_act_before_rd",
                f"RD bank={bank_idx} but state={b.state.value} @ cycle {self.cycle}",
                self.log,
            )
        elif b.last_act_cycle >= 0:
            elapsed = self.cycle - b.last_act_cycle
            if elapsed < self.timings.tRCD_cycles:
                self.policy.report(
                    "tRCD",
                    f"RD bank={bank_idx} only {elapsed} cycles after ACT "
                    f"(needs {self.timings.tRCD_cycles})",
                    self.log,
                )
        # tWTR: WR → RD same bank
        if b.last_wr_data_cycle >= 0:
            elapsed = self.cycle - b.last_wr_data_cycle
            if elapsed < self.timings.tWTR_cycles:
                self.policy.report(
                    "tWTR",
                    f"RD bank={bank_idx} only {elapsed} cycles after last "
                    f"WR data beat (needs {self.timings.tWTR_cycles})",
                    self.log,
                )
        b.last_rd_cycle = self.cycle
        # Read data lands CL cycles later (BL beats total)
        b.last_rd_data_cycle = self.cycle + self.timings.CL + self.timings.BL - 1

    def on_write(self, bank_idx: int) -> None:
        """Process a WR command."""
        self._arm_refi_window()
        self._check_not_refreshing("wr")
        b = self._bank(bank_idx)
        if b.state != BankState.ACTIVE:
            self.policy.report(
                "no_act_before_wr",
                f"WR bank={bank_idx} but state={b.state.value} @ cycle {self.cycle}",
                self.log,
            )
        elif b.last_act_cycle >= 0:
            elapsed = self.cycle - b.last_act_cycle
            if elapsed < self.timings.tRCD_cycles:
                self.policy.report(
                    "tRCD",
                    f"WR bank={bank_idx} only {elapsed} cycles after ACT "
                    f"(needs {self.timings.tRCD_cycles})",
                    self.log,
                )
        b.last_wr_cycle = self.cycle
        # Write data lands CWL cycles later (BL beats total)
        b.last_wr_data_cycle = self.cycle + self.timings.CWL + self.timings.BL - 1

    def on_precharge(self, bank_idx: int, all_banks: bool = False) -> None:
        """Process a PRE command."""
        self._arm_refi_window()
        self._check_not_refreshing("pre")
        targets = self.banks if all_banks else [self._bank(bank_idx)]
        for i, b in enumerate(targets):
            real_idx = i if all_banks else bank_idx
            # tRAS_min: ACT-to-PRE same bank
            if b.last_act_cycle >= 0:
                elapsed = self.cycle - b.last_act_cycle
                if elapsed < self.timings.tRAS_min_cycles:
                    self.policy.report(
                        "tRAS_min",
                        f"PRE bank={real_idx} only {elapsed} cycles after ACT "
                        f"(needs tRAS_min={self.timings.tRAS_min_cycles})",
                        self.log,
                    )
            # tRTP: RD-to-PRE same bank
            if b.last_rd_cycle >= 0:
                elapsed = self.cycle - b.last_rd_cycle
                if elapsed < self.timings.tRTP_cycles:
                    self.policy.report(
                        "tRTP",
                        f"PRE bank={real_idx} only {elapsed} cycles after RD "
                        f"(needs tRTP={self.timings.tRTP_cycles})",
                        self.log,
                    )
            # tWR: end of WR burst to PRE
            if b.last_wr_data_cycle >= 0:
                elapsed = self.cycle - b.last_wr_data_cycle
                if elapsed < self.timings.tWR_cycles:
                    self.policy.report(
                        "tWR",
                        f"PRE bank={real_idx} only {elapsed} cycles after "
                        f"last WR data beat (needs tWR={self.timings.tWR_cycles})",
                        self.log,
                    )
            b.state = BankState.IDLE
            b.row = None
            b.last_pre_cycle = self.cycle

    def on_refresh(self) -> None:
        """Process a REF (all-bank refresh) command."""
        # All banks must be precharged before REF.
        for i, b in enumerate(self.banks):
            if b.state == BankState.ACTIVE:
                self.policy.report(
                    "ref_with_open_row",
                    f"REF issued but bank {i} is ACTIVE (row=0x{b.row:x}) "
                    f"@ cycle {self.cycle}",
                    self.log,
                )
        for b in self.banks:
            b.state = BankState.REFRESHING
            b.row = None
        self._last_ref_cycle = self.cycle
        self._ref_end_cycle = self.cycle + self.timings.tRFC_cycles
        # A REF landed — restart the 9 x tREFI postpone window.
        self._refi_deadline_cycle = (
            self.cycle + 9 * self.timings.tREFI_cycles
        )

    # ----- Helpers -----

    def _bank(self, idx: int) -> Bank:
        if not (0 <= idx < len(self.banks)):
            raise IndexError(f"bank_idx {idx} out of range [0, {len(self.banks)})")
        return self.banks[idx]

    def _check_not_refreshing(self, cmd: str) -> None:
        if any(b.state == BankState.REFRESHING for b in self.banks):
            self.policy.report(
                "cmd_during_refresh",
                f"{cmd.upper()} command issued while refresh in progress "
                f"(REF started cycle {self._last_ref_cycle}, "
                f"ends cycle {self._ref_end_cycle})",
                self.log,
            )

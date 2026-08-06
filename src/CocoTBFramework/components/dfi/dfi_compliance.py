# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI protocol compliance checker — latency-window referee.

The DFI specs define per-interface latency windows that the BFMs
observe but (until now) never enforced. This module turns those rules
into a cycle-fed checker, spec-verified against the v2.1.1-v5.2 books:

  - ``tphy_wrlat``: dfi_wrdata_en must assert exactly tphy_wrlat DFI
    clocks after a write command (v2.1 §3.2; the data itself follows
    one cycle after the enable).
  - ``trddata_en``: dfi_rddata_en must assert exactly trddata_en DFI
    clocks after a read command (v2.1 §3.3).
  - ``tphy_rdlat``: dfi_rddata_valid must assert within tphy_rdlat
    clocks of dfi_rddata_en (maximum PHY read latency, v2.1 §3.3).
  - ``tctrlupd_min`` / ``tctrlupd_max``: the MC-initiated update
    request pulse must be held at least tctrlupd_min and released
    before tctrlupd_max clocks (v2.1 §3.4, Table 8).
  - ``tphyupd_resp``: the MC MUST acknowledge a PHY-initiated update
    request within tphyupd_resp clocks (v2.1 §3.4).
  - ``tinit_start``: a frequency-change offer (init_start asserted
    during normal operation) is ACCEPTED if the PHY de-asserts
    init_complete within tinit_start clocks, otherwise the offer is
    withdrawn. Ignoring the offer is LEGAL — the checker counts
    acknowledged vs not-acknowledged outcomes as statistics, not
    violations.

Architecture mirrors :mod:`dram_state`: a pure-Python core driven by
:meth:`DFIComplianceChecker.on_cycle` with a small per-cycle sample
(unit-testable without a simulator), plus :meth:`attach` — a cocotb
coroutine that samples a standard ``mc_dfi``-style bus every clock and
feeds the core. Violations accumulate in counters and records; they
never raise, so the checker can referee a failing DUT to the end of
the test.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, FrozenSet, List, Optional, Tuple

# All known rule names (the enabled_rules default).
RULE_TPHY_WRLAT = "tphy_wrlat"
RULE_TRDDATA_EN = "trddata_en"
RULE_TPHY_RDLAT = "tphy_rdlat"
RULE_TCTRLUPD_MIN = "tctrlupd_min"
RULE_TCTRLUPD_MAX = "tctrlupd_max"
RULE_TPHYUPD_RESP = "tphyupd_resp"

ALL_RULES: FrozenSet[str] = frozenset({
    RULE_TPHY_WRLAT, RULE_TRDDATA_EN, RULE_TPHY_RDLAT,
    RULE_TCTRLUPD_MIN, RULE_TCTRLUPD_MAX, RULE_TPHYUPD_RESP,
})


@dataclass(frozen=True)
class DFIComplianceParams:
    """Programmable-parameter values the checker referees against.

    These are the DFI *programmable parameters* — system-chosen within
    spec-defined ranges — so there are no universal defaults; the
    values here match the BFM's legacy timing profile (wrlat 0,
    rddata_en CL-ish handled by the testbench). Set them to whatever
    the DUT configuration programs.
    """

    tphy_wrlat: int = 0
    trddata_en: int = 1
    tphy_rdlat: int = 4
    tctrlupd_min: int = 1
    tctrlupd_max: int = 32
    tphyupd_resp: int = 8
    tinit_start: int = 8
    enabled_rules: FrozenSet[str] = ALL_RULES


@dataclass(frozen=True)
class CycleSample:
    """One DFI clock's worth of observed wire state (post-decode).

    ``wr_cmd`` / ``rd_cmd`` are the decoded command strobes for this
    cycle (the attach loop derives them from cs_n + ras/cas/we);
    everything else is the raw wire level.
    """

    wr_cmd: bool = False
    rd_cmd: bool = False
    wrdata_en: bool = False
    rddata_en: bool = False
    rddata_valid: bool = False
    ctrlupd_req: bool = False
    phyupd_req: bool = False
    phyupd_ack: bool = False
    init_start: bool = False
    init_complete: bool = False


@dataclass(frozen=True)
class ComplianceViolation:
    rule: str
    cycle: int
    message: str


class DFIComplianceChecker:
    """Latency-window referee for one DFI channel.

    Feed one :class:`CycleSample` per DFI clock via :meth:`on_cycle`,
    or let :meth:`attach` do the sampling from a cocotb bus. Read
    results from :attr:`violations` / :meth:`report` and the
    frequency-change outcome stats.
    """

    def __init__(
        self,
        params: Optional[DFIComplianceParams] = None,
        log: Optional[logging.Logger] = None,
    ):
        self.params = params if params is not None else DFIComplianceParams()
        self.log = log
        self.cycle = 0

        self.violations: List[ComplianceViolation] = []
        self.counts: Dict[str, int] = {}

        # Frequency-change outcome statistics (NOT violations).
        self.freq_change_acknowledged = 0
        self.freq_change_not_acknowledged = 0

        # Pending expectations, as (due_cycle, origin_cycle) queues.
        self._wrlat_due: Deque[Tuple[int, int]] = deque()
        self._rden_due: Deque[Tuple[int, int]] = deque()
        # rddata_valid windows: (deadline_cycle, origin_cycle)
        self._rdlat_deadline: Deque[Tuple[int, int]] = deque()

        # ctrlupd pulse tracking
        self._ctrlupd_assert_cycle: Optional[int] = None
        # phyupd response tracking
        self._phyupd_assert_cycle: Optional[int] = None
        # freq-change offer tracking
        self._init_start_offer_cycle: Optional[int] = None

        self._prev = CycleSample()

    # ----- Reporting -----

    def _flag(self, rule: str, message: str) -> None:
        if rule not in self.params.enabled_rules:
            return
        self.violations.append(
            ComplianceViolation(rule=rule, cycle=self.cycle, message=message)
        )
        self.counts[rule] = self.counts.get(rule, 0) + 1
        if self.log is not None:
            self.log.warning("DFI compliance [%s] @ %d: %s",
                             rule, self.cycle, message)

    def report(self) -> Dict[str, int]:
        """Violation counts by rule (empty dict = fully compliant)."""
        return dict(self.counts)

    def assert_clean(self) -> None:
        """Raise AssertionError listing violations, if any."""
        assert not self.violations, (
            f"{len(self.violations)} DFI compliance violations: "
            f"{self.report()}; first: {self.violations[0]}"
        )

    # ----- Core: one DFI clock -----

    def on_cycle(self, s: CycleSample) -> None:
        p = self.params
        prev = self._prev
        self.cycle += 1

        # --- Write path: WR @ c => wrdata_en @ c + tphy_wrlat ---
        if s.wr_cmd:
            self._wrlat_due.append((self.cycle + p.tphy_wrlat, self.cycle))
        expected_wren = bool(
            self._wrlat_due and self._wrlat_due[0][0] == self.cycle
        )
        if expected_wren:
            due, origin = self._wrlat_due.popleft()
            if not s.wrdata_en:
                self._flag(
                    RULE_TPHY_WRLAT,
                    f"wrdata_en not asserted {p.tphy_wrlat} cycles after "
                    f"the WR command @ {origin}",
                )
        elif s.wrdata_en and not prev.wrdata_en and p.tphy_wrlat > 0:
            # Rising wrdata_en with no write due this cycle. (With
            # wrlat=0 the enable is level-driven by the BFM around the
            # command, so orphan detection only applies for wrlat > 0.)
            self._flag(
                RULE_TPHY_WRLAT,
                "wrdata_en asserted with no write command "
                f"{p.tphy_wrlat} cycles earlier",
            )

        # --- Read path: RD @ c => rddata_en @ c + trddata_en ---
        if s.rd_cmd:
            self._rden_due.append((self.cycle + p.trddata_en, self.cycle))
        if self._rden_due and self._rden_due[0][0] == self.cycle:
            due, origin = self._rden_due.popleft()
            if not s.rddata_en:
                self._flag(
                    RULE_TRDDATA_EN,
                    f"rddata_en not asserted {p.trddata_en} cycles after "
                    f"the RD command @ {origin}",
                )

        # --- Read latency: rddata_en rise => rddata_valid within
        #     tphy_rdlat ---
        if s.rddata_en and not prev.rddata_en:
            self._rdlat_deadline.append(
                (self.cycle + p.tphy_rdlat, self.cycle)
            )
        if s.rddata_valid:
            if self._rdlat_deadline:
                self._rdlat_deadline.popleft()
        while (self._rdlat_deadline
               and self._rdlat_deadline[0][0] < self.cycle):
            deadline, origin = self._rdlat_deadline.popleft()
            self._flag(
                RULE_TPHY_RDLAT,
                f"rddata_valid did not assert within tphy_rdlat="
                f"{p.tphy_rdlat} of rddata_en @ {origin}",
            )

        # --- ctrlupd pulse width: [tctrlupd_min, tctrlupd_max] ---
        if s.ctrlupd_req and not prev.ctrlupd_req:
            self._ctrlupd_assert_cycle = self.cycle
        if not s.ctrlupd_req and prev.ctrlupd_req:
            if self._ctrlupd_assert_cycle is not None:
                width = self.cycle - self._ctrlupd_assert_cycle
                if width < p.tctrlupd_min:
                    self._flag(
                        RULE_TCTRLUPD_MIN,
                        f"ctrlupd_req held {width} < tctrlupd_min="
                        f"{p.tctrlupd_min} cycles",
                    )
                self._ctrlupd_assert_cycle = None
        if (s.ctrlupd_req and self._ctrlupd_assert_cycle is not None
                and self.cycle - self._ctrlupd_assert_cycle
                == p.tctrlupd_max + 1):
            self._flag(
                RULE_TCTRLUPD_MAX,
                f"ctrlupd_req still asserted after tctrlupd_max="
                f"{p.tctrlupd_max} cycles",
            )

        # --- phyupd response: ack within tphyupd_resp of req ---
        if s.phyupd_req and not prev.phyupd_req:
            self._phyupd_assert_cycle = self.cycle
        if s.phyupd_ack:
            self._phyupd_assert_cycle = None
        elif (self._phyupd_assert_cycle is not None
                and self.cycle - self._phyupd_assert_cycle
                == p.tphyupd_resp + 1):
            self._flag(
                RULE_TPHYUPD_RESP,
                f"phyupd_ack not asserted within tphyupd_resp="
                f"{p.tphyupd_resp} cycles of phyupd_req",
            )
            self._phyupd_assert_cycle = None
        if not s.phyupd_req:
            self._phyupd_assert_cycle = None

        # --- Frequency-change outcome (statistic, not a violation) ---
        if (s.init_start and not prev.init_start and s.init_complete):
            self._init_start_offer_cycle = self.cycle
        if self._init_start_offer_cycle is not None:
            if not s.init_complete:
                self.freq_change_acknowledged += 1
                self._init_start_offer_cycle = None
            elif not s.init_start:
                # Offer withdrawn before acceptance
                self.freq_change_not_acknowledged += 1
                self._init_start_offer_cycle = None
            elif (self.cycle - self._init_start_offer_cycle
                    > self.params.tinit_start):
                self.freq_change_not_acknowledged += 1
                self._init_start_offer_cycle = None

        self._prev = s

    # ----- cocotb integration -----

    async def attach(self, bus: Any, clock: Any) -> None:
        """Sample an ``mc_dfi``-style bus each falling clock edge and
        feed :meth:`on_cycle`. Run with ``cocotb.start_soon``.

        Command strobes are decoded from cs_n + (ras_n, cas_n, we_n)
        with the same JESD79-3-style table the DFIMonitor uses.
        """
        from cocotb.triggers import FallingEdge

        from .dfi_monitor import _CMD_DECODE, _v
        from .dfi_packet import DRAMCommand

        while True:
            await FallingEdge(clock)
            cmd = DRAMCommand.NOP
            if _v(bus.cs_n) == 0:
                cmd = _CMD_DECODE.get(
                    (_v(bus.ras_n), _v(bus.cas_n), _v(bus.we_n)),
                    DRAMCommand.NOP,
                )
            self.on_cycle(CycleSample(
                wr_cmd=(cmd == DRAMCommand.WR),
                rd_cmd=(cmd == DRAMCommand.RD),
                wrdata_en=bool(_v(bus.wrdata_en)),
                rddata_en=bool(_v(bus.rddata_en)),
                rddata_valid=bool(_v(bus.rddata_valid)),
                ctrlupd_req=bool(_v(bus.ctrlupd_req)),
                phyupd_req=bool(_v(bus.phyupd_req)),
                phyupd_ack=bool(_v(bus.phyupd_ack)),
                init_start=bool(_v(bus.init_start)),
                init_complete=bool(_v(bus.init_complete)),
            ))

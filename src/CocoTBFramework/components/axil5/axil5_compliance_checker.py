# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5ComplianceChecker
# Purpose: AXI4-Lite compliance plus the AXI5-Lite optional-group rules
#
# Subsystem: framework

"""AXI5-Lite protocol compliance checking.

``AXIL4ComplianceChecker`` plus the rules that only exist once the optional
signal groups are present. Everything AXI4-Lite checks -- handshake stability,
address alignment, response codes, strobes, PROT -- is inherited unchanged,
because AXI5-Lite does not alter a single one of those rules.

Until now AXIL5 interfaces constructed an ``AXIL4ComplianceChecker``. That was
correct as far as it went and it is why this class subclasses rather than
replaces: the shared rules had a working implementation and a second copy would
have drifted. What it could not do is check anything about the optional groups,
because AXI4-Lite has none.

The added rules, and why each one is a rule:

* **Sideband stability.** AWID/AWUSER/AWTRACE and friends are qualified by
  AWVALID exactly as AWADDR is, so they must hold from VALID assertion until
  the handshake completes. A DUT that lets AWID wobble mid-handshake presents
  two different IDs for one transaction and the completer may latch either.
  AXI4-Lite already checks this for ADDR and DATA; the AXI5-Lite signals need
  the same treatment.
* **ID reflection.** A Subordinate returns BID/RID equal to the AWID/ARID of
  the request it answers (IHI 0022L A5.1.1: "the Manager requires BID and RID
  to be reflected from AWID and ARID"). Responses to different IDs may be
  reordered, so the check is against the set of IDs outstanding, not the last
  one issued.
* **POISON without data.** WPOISON qualifies write data; RPOISON qualifies read
  data. Poison asserted on a beat whose strobes are all zero marks bytes that
  were never written.
* **No EXOKAY.** AXI5-Lite does not support exclusive accesses (B2.1.5) and has
  no AxLOCK (Table B2.2), so an EXOKAY response can never be legitimate.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from CocoTBFramework.components.axil4.axil4_compliance_checker import (
    AXIL4ComplianceChecker,
    AXIL4Violation,
)


class AXIL5ViolationType(Enum):
    """AXI5-Lite violations, beyond everything ``AXIL4ViolationType`` lists.

    A separate enum rather than added members, because AXIL4ViolationType is
    consumed by the AXI4-Lite checker and its report formatting; growing it
    with values AXI4-Lite can never emit would make those reports claim a
    coverage they do not have.
    """
    SIDEBAND_UNSTABLE = "sideband_unstable"
    ID_NOT_REFLECTED = "id_not_reflected"
    POISON_WITHOUT_DATA = "poison_without_data"
    EXCLUSIVE_RESPONSE_UNEXPECTED = "exclusive_response_unexpected"


@dataclass
class AXIL5Violation(AXIL4Violation):
    """An AXIL4 violation record; the type may come from either enum."""


class AXIL5ComplianceChecker(AXIL4ComplianceChecker):
    """AXI4-Lite compliance, plus the optional-group rules.

    Constructed through :meth:`create_if_enabled` exactly like the AXI4-Lite
    one, so enabling compliance checking is the same environment switch for
    both families.
    """

    #: Address-channel groups that must hold steady while VALID is asserted.
    STABLE_ADDR_SIDEBAND = ('id', 'user', 'trace')
    #: Data-channel groups with the same requirement.
    STABLE_DATA_SIDEBAND = ('user', 'poison')

    def __init__(self, dut, clock, prefix="", log=None, **kwargs):
        super().__init__(dut, clock, prefix=prefix, log=log, **kwargs)
        # Which groups this DUT actually carries. A group the RTL was built
        # without is not a violation, it is absent -- so every added check
        # below is skipped rather than failed when the signal is not there.
        self._sideband_present: Dict[str, bool] = {}
        self._ids_outstanding: Dict[str, List[Any]] = {'aw': [], 'ar': []}

    # -- helpers ---------------------------------------------------------

    def _signal(self, name: str):
        """Return the DUT signal for ``prefix + name``, or None if absent."""
        full = f"{self.prefix}{name}" if self.prefix else name
        return getattr(self.dut, full, None)

    def has_sideband(self, channel: str, field: str) -> bool:
        """True when this DUT carries ``{channel}{field}``.

        Cached: an ENABLE_* parameter is fixed at elaboration, so a group
        cannot appear part-way through a run.
        """
        key = f"{channel}{field}"
        if key not in self._sideband_present:
            self._sideband_present[key] = self._signal(key) is not None
        return self._sideband_present[key]

    # -- the AXI5-Lite rules ---------------------------------------------

    def check_sideband_stability(self, channel: str, field: str,
                                 previous: Any, current: Any) -> bool:
        """Optional-group values must not change during ``valid && !ready``.

        Returns True when compliant (including when the group is absent).
        """
        if not self.has_sideband(channel, field):
            return True
        if previous is None or previous == current:
            return True
        self.record_violation(
            AXIL5ViolationType.SIDEBAND_UNSTABLE, channel,
            f"{channel}{field} changed from {previous} to {current} while "
            f"{channel}valid was asserted and {channel}ready was low; the "
            f"completer may latch either value",
        )
        return False

    def note_id_issued(self, channel: str, value: Any) -> None:
        """Record an AWID/ARID accepted on ``channel`` ('aw' or 'ar')."""
        self._ids_outstanding[channel].append(value)

    def check_id_reflected(self, response_channel: str, value: Any) -> bool:
        """B/R ID must equal the AW/AR ID of an outstanding request.

        Responses to DIFFERENT IDs may return in any order, so the response
        matches any outstanding request carrying that ID; the oldest such
        request is retired.
        """
        issued_from = 'aw' if response_channel == 'b' else 'ar'
        if not self.has_sideband(response_channel, 'id'):
            return True
        pending = self._ids_outstanding[issued_from]
        if not pending:
            return True
        if value in pending:
            pending.remove(value)
            return True
        self.record_violation(
            AXIL5ViolationType.ID_NOT_REFLECTED, response_channel,
            f"{response_channel}id returned {value}, but no {issued_from}id "
            f"with that value is outstanding (outstanding: {pending}); the "
            f"Manager cannot match this response to its request",
        )
        return False

    def check_poison_has_data(self, channel: str, poison: Any, strb: Any) -> bool:
        """POISON marks bytes that were actually transferred.

        Only meaningful on W, where strobes exist. R has no strobes, so a
        poisoned read beat is always well-formed.
        """
        if not self.has_sideband(channel, 'poison') or not poison:
            return True
        if channel == 'w' and strb is not None and int(strb) == 0:
            self.record_violation(
                AXIL5ViolationType.POISON_WITHOUT_DATA, channel,
                f"wpoison={poison} with wstrb=0: poison marks bytes that "
                f"were never written",
            )
            return False
        return True

    def check_exclusive_response(self, resp: int) -> bool:
        """EXOKAY (0b01) is never legal on AXI5-Lite.

        Exclusive accesses are not supported (IHI 0022L B2.1.5) and AxLOCK is
        not present (Table B2.2), so no request can have asked for one.
        """
        if resp != 1:
            return True
        self.record_violation(
            AXIL5ViolationType.EXCLUSIVE_RESPONSE_UNEXPECTED, 'b',
            "EXOKAY returned on an AXI5-Lite interface; AXI5-Lite has no "
            "exclusive access, so no response can legitimately be EXOKAY",
        )
        return False

"""The compliance checkers must build their channel monitors the way the
BFMs do -- with a protocol_type, which carries the optional-field set -- and
must not swallow a setup failure. Both defects were found 2026-09-09: without
protocol_type every AXI5 sideband field was required, setup failed on any
real port, the checker logged a warning and disabled itself, and its report
read as zero violations. Vacuous for a month."""
from __future__ import annotations

import inspect
import re

import pytest

from CocoTBFramework.components.axi4.axi4_compliance_checker import AXI4ComplianceChecker
from CocoTBFramework.components.axi5.axi5_compliance_checker import AXI5ComplianceChecker


@pytest.mark.parametrize("cls,fam", [(AXI4ComplianceChecker, "axi4"), (AXI5ComplianceChecker, "axi5")])
def test_every_channel_monitor_names_its_protocol_type(cls, fam):
    src = inspect.getsource(cls.setup_monitors)
    # One block per channel: from its assignment to the next assignment (or
    # the tail of the function). A parenthesis-matching regex stops at the
    # nested field_config(...) call and misses the kwargs after it.
    starts = [m.start() for m in re.finditer(r"self\.monitors\['(AR|AW|W|R|B)'\] = GAXIMonitor\(", src)]
    assert len(starts) == 5, f"expected 5 channel monitors, found {len(starts)}"
    ends = starts[1:] + [src.find("for monitor in self.monitors.values()")]
    for a, b in zip(starts, ends):
        block = src[a:b]
        m = re.search(r"protocol_type='(%s_(ar|aw|w|r|b)_(master|slave))'" % fam, block)
        assert m, f"a {fam} channel monitor has no protocol_type:\n{block}"


@pytest.mark.parametrize("cls", [AXI4ComplianceChecker, AXI5ComplianceChecker])
def test_setup_failure_raises_instead_of_disabling(cls):
    src = inspect.getsource(cls.setup_monitors)
    assert "raise RuntimeError" in src
    assert "Could not setup" not in src or "raise" in src.split("Could not setup")[0]

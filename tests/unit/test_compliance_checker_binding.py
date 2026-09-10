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


@pytest.mark.parametrize("cls", [AXI4ComplianceChecker, AXI5ComplianceChecker])
def test_channel_prefix_tolerates_a_missing_separator(cls):
    """A port prefix may or may not carry its separator -- the bridge writes
    "cpu_rd_axi_" for one fixture and "cpu_m_axi" for another. Naive
    concatenation found no channels on the second, so the checker built no
    monitors and still reported zero violations: armed and blind reads exactly
    like clean (found 2026-09-10, bridge_2x2_rw, 0 violations in 0 checks).

    Built with object.__new__ so the resolution is tested on its own -- a real
    construction sets up the channel monitors, which needs a full signal set.
    """
    class _DUT:
        pass
    dut = _DUT()
    for sig in ('arvalid', 'arready', 'awvalid', 'awready'):
        setattr(dut, f'cpu_m_axi_{sig}', object())

    chk = object.__new__(cls)
    chk.dut = dut
    chk.prefix = 'cpu_m_axi'          # no trailing separator
    chk._resolved_prefix = None
    assert chk._channel_prefix() == 'cpu_m_axi_'
    assert chk._has_channel_signals('ar')
    assert chk._has_channel_signals('aw')
    assert not chk._has_channel_signals('r')   # not present on this mock

    # A prefix that already carries its separator is unchanged.
    chk2 = object.__new__(cls)
    chk2.dut = dut
    chk2.prefix = 'cpu_m_axi_'
    chk2._resolved_prefix = None
    assert chk2._channel_prefix() == 'cpu_m_axi_'


@pytest.mark.parametrize("cls", [AXI4ComplianceChecker, AXI5ComplianceChecker])
def test_report_says_whether_it_is_armed(cls):
    """'zero violations' is only meaningful with something behind it."""
    src = inspect.getsource(cls.get_compliance_report)
    assert "'armed'" in src and "'channels'" in src

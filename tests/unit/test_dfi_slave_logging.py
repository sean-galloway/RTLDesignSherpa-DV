"""DFISlavePHY command logging.

The AXI slaves log a transaction with every field that decides what
they do (id, addr, len, size, resp). The DFI equivalent is the command
plus the bank state it acts on, and — when the command arrived on an
encoded CA bus — the decoded fields, which the legacy `(bank, addr)`
fold discards. Without them a trace of an HBM4 or LPDDR5 run cannot say
which pseudo-channel, sub-channel or stack ID a command targeted, which
is the first thing you want when a burst lands in the wrong place.

`DFISlavePHY` needs a live cocotb entity, so these run the log helper on
a bare instance carrying only what it touches, as the other slave glue
tests do.
"""

import logging

import pytest

from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY


class _Bank:
    def __init__(self, row=0x1234):
        self.row = row


class _Dram:
    def __init__(self, rows=None):
        self.banks = [_Bank(r) for r in (rows or [0x1234] * 16)]


def _slave(ca_args=None, lpddr_args=None, ca_installed=False, rows=None):
    s = object.__new__(DFISlavePHY)
    s.dram = _Dram(rows)
    s.log = logging.getLogger("dfi-slave-logging-test")
    s._ca_streams = object() if ca_installed else None
    s._ca_args = ca_args
    s._lpddr_args = lpddr_args
    return s


def _capture(caplog, slave, cmd, bank, addr, cycle=100):
    caplog.clear()
    with caplog.at_level(logging.INFO):
        slave._log_command(cmd, bank, addr, cycle)
    assert caplog.records, "no log record emitted"
    return caplog.records[-1].getMessage()


def test_logs_command_bank_and_open_row(caplog):
    s = _slave(rows=[0xABC] * 16)
    msg = _capture(caplog, s, DRAMCommand.ACT, 3, 0xABC)
    assert "DFISlavePHY:" in msg
    assert "ACT" in msg
    assert "bank=3" in msg
    assert "open_row=0xABC" in msg
    assert "cyc=100" in msg


def test_ca_fields_reach_the_log_line(caplog):
    """The point of the change: selectors survive into the trace."""
    s = _slave(ca_installed=True,
               ca_args={"bank": 6, "row": 0x2A5, "pc": 1, "sid": 2, "sc": 0})
    msg = _capture(caplog, s, DRAMCommand.ACT, 6, 0x2A5)
    assert "row=0x2A5" in msg
    assert "pc=1" in msg and "sid=2" in msg and "sc=0" in msg


def test_column_command_shows_col_and_auto_precharge(caplog):
    s = _slave(ca_installed=True,
               ca_args={"bank": 9, "col": 17, "auto_precharge": True})
    msg = _capture(caplog, s, DRAMCommand.WRA, 9, 17)
    assert "col=0x11" in msg
    assert "auto_precharge=True" in msg


def test_legacy_path_logs_without_ca_fields(caplog):
    """ras/cas/we commands have no decoded args; the line still forms."""
    s = _slave(ca_installed=False)
    msg = _capture(caplog, s, DRAMCommand.REF, 0, 0)
    assert "REF" in msg
    assert "pc=" not in msg and "sid=" not in msg


def test_lpddr2_args_are_used_when_no_ca_map(caplog):
    """LPDDR2 decodes through the older path but still has args."""
    s = _slave(ca_installed=False, lpddr_args={"bank": 2, "row": 0x55})
    msg = _capture(caplog, s, DRAMCommand.ACT, 2, 0x55)
    assert "row=0x55" in msg


def test_bank_beyond_model_does_not_raise(caplog):
    """A decode can name a bank the model does not have; logging must
    report it rather than throw, since this runs inside the sim loop."""
    s = _slave(rows=[0x10] * 2)
    msg = _capture(caplog, s, DRAMCommand.PRE, 9, 0)
    assert "bank=9" in msg
    assert "open_row=closed" in msg


def test_sim_time_helper_survives_no_simulator():
    """Logging must never be what kills a run. Outside a simulation
    get_sim_time() raises, so the helper degrades to '-'."""
    assert DFISlavePHY._sim_time_ns() == "-"


@pytest.mark.parametrize("cls_name,module", [
    ("DFISlavePHY", "dfi_slave_phy"),
    ("DFIMonitor", "dfi_monitor"),
    ("DFIMasterMC", "dfi_master_mc"),
])
def test_components_accept_an_injected_logger(cls_name, module):
    """A testbench must be able to hand these its TBBase logger.

    Each of these used to pin `self.log` to the cocotb entity logger
    unconditionally, so DFI output landed somewhere other than the log
    file holding the transactions that caused it.
    """
    import importlib
    import inspect

    cls = getattr(importlib.import_module(
        f"CocoTBFramework.components.dfi.{module}"), cls_name)
    params = inspect.signature(cls.__init__).parameters
    assert "log" in params, f"{cls_name} takes no log= argument"
    assert params["log"].default is None, \
        f"{cls_name}'s log= must default to the entity logger"

"""Unit tests for scoreboards/axi4_scoreboard.py.

Proves the repaired monitor wiring and field access:
- add_master_monitor / add_slave_monitor accept framework monitors that only
  provide add_callback() (GAXIMonitor / cocotb_bus BusMonitor style), with a
  fallback to custom monitors exposing set_write_callback/set_read_callback.
- Match logic resolves both generic framework field names ('addr', 'data',
  'resp', ...) and AXI-prefixed names ('awaddr', 'wdata', 'bresp', ...), so
  real mismatches are detected instead of silently skipped.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from CocoTBFramework.scoreboards.axi4_scoreboard import AXI4Scoreboard

# ---------------------------------------------------------------------------
# Test doubles and packet builders
# ---------------------------------------------------------------------------

class FrameworkStyleMonitor:
    """Mimics GAXIMonitor / cocotb_bus Monitor: add_callback(cb), cb(transaction)."""

    def __init__(self):
        self._callbacks = []

    def add_callback(self, callback):
        self._callbacks.append(callback)

    def emit(self, transaction):
        for callback in self._callbacks:
            callback(transaction)


class CustomStyleMonitor:
    """Mimics a custom monitor exposing set_write_callback/set_read_callback."""

    def __init__(self):
        self.write_callback = None
        self.read_callback = None

    def set_write_callback(self, callback):
        self.write_callback = callback

    def set_read_callback(self, callback):
        self.read_callback = callback

    def emit_write(self, id_value, transaction):
        self.write_callback(id_value, transaction)

    def emit_read(self, id_value, transaction):
        self.read_callback(id_value, transaction)


class NoCallbackMonitor:
    """Monitor with no supported callback mechanism."""


def make_write_tx(addr=0x1000, data=(0xDEADBEEF, 0x12345678), resp=0,
                  id_value=3, length=None, size=2, burst=1, prefixed=False):
    """Build a composite write transaction using generic or AXI-prefixed names."""
    length = length if length is not None else len(data) - 1
    if prefixed:
        aw = SimpleNamespace(awid=id_value, awaddr=addr, awlen=length,
                             awsize=size, awburst=burst)
        w = [SimpleNamespace(wdata=d) for d in data]
        b = SimpleNamespace(bid=id_value, bresp=resp)
    else:
        aw = SimpleNamespace(id=id_value, addr=addr, len=length,
                             size=size, burst=burst)
        w = [SimpleNamespace(data=d) for d in data]
        b = SimpleNamespace(id=id_value, resp=resp)
    return {'aw_transaction': aw, 'w_transactions': w, 'b_transaction': b}


def make_read_tx(addr=0x2000, data=(0x11, 0x22), resp=0, id_value=5,
                 length=None, size=2, burst=1, prefixed=False):
    """Build a composite read transaction using generic or AXI-prefixed names."""
    length = length if length is not None else len(data) - 1
    if prefixed:
        ar = SimpleNamespace(arid=id_value, araddr=addr, arlen=length,
                             arsize=size, arburst=burst)
        r = [SimpleNamespace(rid=id_value, rdata=d, rresp=resp) for d in data]
    else:
        ar = SimpleNamespace(id=id_value, addr=addr, len=length,
                             size=size, burst=burst)
        r = [SimpleNamespace(id=id_value, data=d, resp=resp) for d in data]
    return {'ar_transaction': ar, 'r_transactions': r}


# ---------------------------------------------------------------------------
# Monitor wiring
# ---------------------------------------------------------------------------

class TestMonitorWiring:
    def test_framework_monitor_add_callback_is_used(self):
        sb = AXI4Scoreboard("sb")
        master = FrameworkStyleMonitor()
        slave = FrameworkStyleMonitor()
        sb.add_master_monitor(master)
        sb.add_slave_monitor(slave)
        assert len(master._callbacks) == 1
        assert len(slave._callbacks) == 1

        master.emit(make_write_tx())
        slave.emit(make_write_tx())
        assert sb.write_count == 1
        assert sb.error_count == 0

    def test_framework_monitor_routes_reads(self):
        sb = AXI4Scoreboard("sb")
        master = FrameworkStyleMonitor()
        slave = FrameworkStyleMonitor()
        sb.add_master_monitor(master)
        sb.add_slave_monitor(slave)

        master.emit(make_read_tx())
        slave.emit(make_read_tx())
        assert sb.read_count == 1
        assert sb.error_count == 0

    def test_id_extracted_from_channel_packet(self):
        """Composite tx without an 'id' key gets its ID from the AW packet."""
        sb = AXI4Scoreboard("sb")
        master = FrameworkStyleMonitor()
        sb.add_master_monitor(master)
        master.emit(make_write_tx(id_value=7, prefixed=True))
        assert 7 in sb.master_writes

    def test_custom_monitor_set_callbacks_still_supported(self):
        sb = AXI4Scoreboard("sb")
        master = CustomStyleMonitor()
        slave = CustomStyleMonitor()
        sb.add_master_monitor(master)
        sb.add_slave_monitor(slave)
        assert master.write_callback is not None
        assert slave.read_callback is not None

        master.emit_write(3, make_write_tx(id_value=3))
        slave.emit_write(3, make_write_tx(id_value=3))
        assert sb.write_count == 1
        assert sb.error_count == 0

        master.emit_read(5, make_read_tx(id_value=5))
        slave.emit_read(5, make_read_tx(id_value=5))
        assert sb.read_count == 1
        assert sb.error_count == 0

    def test_monitor_without_callback_support_raises(self):
        sb = AXI4Scoreboard("sb")
        with pytest.raises(ValueError, match="neither"):
            sb.add_master_monitor(NoCallbackMonitor())

    def test_unclassifiable_transaction_is_ignored(self):
        sb = AXI4Scoreboard("sb")
        master = FrameworkStyleMonitor()
        sb.add_master_monitor(master)
        master.emit({'unrelated': 1})
        assert sb.master_writes == {}
        assert sb.master_reads == {}


# ---------------------------------------------------------------------------
# Write match / mismatch detection
# ---------------------------------------------------------------------------

class TestWriteMatching:
    def _run(self, master_tx, slave_tx):
        sb = AXI4Scoreboard("sb")
        master = FrameworkStyleMonitor()
        slave = FrameworkStyleMonitor()
        sb.add_master_monitor(master)
        sb.add_slave_monitor(slave)
        master.emit(master_tx)
        slave.emit(slave_tx)
        return sb

    def test_match_with_generic_field_names(self):
        sb = self._run(make_write_tx(), make_write_tx())
        assert sb.write_count == 1
        assert sb.error_count == 0
        assert sb.check_all_transactions_matched()

    def test_match_with_prefixed_field_names(self):
        sb = self._run(make_write_tx(prefixed=True), make_write_tx(prefixed=True))
        assert sb.write_count == 1
        assert sb.error_count == 0

    def test_match_with_mixed_field_names(self):
        """Master uses AXI-prefixed names, slave uses generic names."""
        sb = self._run(make_write_tx(prefixed=True), make_write_tx(prefixed=False))
        assert sb.write_count == 1
        assert sb.error_count == 0

    def test_address_mismatch_detected(self):
        sb = self._run(make_write_tx(addr=0x1000), make_write_tx(addr=0x2000))
        assert sb.error_count == 1
        assert sb.write_count == 0
        assert not sb.check_all_transactions_matched()

    def test_address_mismatch_detected_across_naming_styles(self):
        sb = self._run(make_write_tx(addr=0x1000, prefixed=True),
                       make_write_tx(addr=0x2000, prefixed=False))
        assert sb.error_count == 1
        assert sb.write_count == 0

    def test_data_mismatch_detected(self):
        sb = self._run(make_write_tx(data=(0xAAAA, 0xBBBB)),
                       make_write_tx(data=(0xAAAA, 0xCCCC)))
        assert sb.error_count == 1
        assert sb.write_count == 0

    def test_beat_count_mismatch_detected(self):
        sb = self._run(make_write_tx(data=(0x1, 0x2), length=1),
                       make_write_tx(data=(0x1,), length=1))
        assert sb.error_count == 1

    def test_response_mismatch_detected(self):
        sb = self._run(make_write_tx(resp=0), make_write_tx(resp=2))
        assert sb.error_count == 1

    def test_burst_params_mismatch_detected(self):
        sb = self._run(make_write_tx(size=2, burst=1),
                       make_write_tx(size=3, burst=1))
        assert sb.error_count == 1

    def test_missing_aw_on_one_side_detected(self):
        slave_tx = make_write_tx()
        del slave_tx['aw_transaction']
        sb = self._run(make_write_tx(), slave_tx)
        assert sb.error_count == 1


# ---------------------------------------------------------------------------
# Read match / mismatch detection
# ---------------------------------------------------------------------------

class TestReadMatching:
    def _run(self, master_tx, slave_tx):
        sb = AXI4Scoreboard("sb")
        master = FrameworkStyleMonitor()
        slave = FrameworkStyleMonitor()
        sb.add_master_monitor(master)
        sb.add_slave_monitor(slave)
        master.emit(master_tx)
        slave.emit(slave_tx)
        return sb

    def test_match_with_generic_field_names(self):
        sb = self._run(make_read_tx(), make_read_tx())
        assert sb.read_count == 1
        assert sb.error_count == 0
        assert sb.check_all_transactions_matched()

    def test_match_with_mixed_field_names(self):
        sb = self._run(make_read_tx(prefixed=False), make_read_tx(prefixed=True))
        assert sb.read_count == 1
        assert sb.error_count == 0

    def test_address_mismatch_detected(self):
        sb = self._run(make_read_tx(addr=0x2000), make_read_tx(addr=0x3000))
        assert sb.error_count == 1
        assert sb.read_count == 0

    def test_data_mismatch_detected_across_naming_styles(self):
        sb = self._run(make_read_tx(data=(0x11, 0x22), prefixed=True),
                       make_read_tx(data=(0x11, 0x33), prefixed=False))
        assert sb.error_count == 1
        assert sb.read_count == 0

    def test_length_mismatch_detected(self):
        sb = self._run(make_read_tx(length=3), make_read_tx(length=1))
        assert sb.error_count == 1


# ---------------------------------------------------------------------------
# Reporting / bookkeeping
# ---------------------------------------------------------------------------

class TestReporting:
    def test_report_and_clear(self):
        sb = AXI4Scoreboard("sb")
        master = FrameworkStyleMonitor()
        slave = FrameworkStyleMonitor()
        sb.add_master_monitor(master)
        sb.add_slave_monitor(slave)

        master.emit(make_write_tx())
        slave.emit(make_write_tx())
        master.emit(make_read_tx())
        slave.emit(make_read_tx(addr=0x9999))  # mismatch

        report = sb.report()
        assert "Write transactions matched: 1" in report
        assert "Data mismatches: 1" in report

        sb.clear()
        assert sb.write_count == 0
        assert sb.read_count == 0
        assert sb.error_count == 0
        assert sb.master_writes == {}
        assert sb.check_all_transactions_matched()

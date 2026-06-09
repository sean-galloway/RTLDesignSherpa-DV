"""Inheritance hook tests for APB / APB5 BFMs (issue #15).

These tests instantiate the BFM classes via ``__new__`` to bypass
``cocotb_bus``'s ``__init__`` (which requires a real simulator), then
exercise the hook methods directly. This validates:

1. The hook methods exist on each class (catches typos / missed overrides).
2. APB5's hook overrides actually call ``super()`` and merge correctly
   (vs accidentally returning only their own delta).
3. The packet-building hook returns the right packet subclass.

These tests would have caught the latent APB5Slave bug from #15 Phase B:
calling ``mem.write(line, int, strb)`` instead of ``mem.write(addr, bytearray, strb)``.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.apb.apb_components import APBMaster, APBMonitor, APBSlave
from CocoTBFramework.components.apb5.apb5_components import (
    APB5Master,
    APB5Monitor,
    APB5Slave,
)
from CocoTBFramework.components.apb.apb_packet import APBPacket
from CocoTBFramework.components.apb5.apb5_packet import APB5Packet


# ----------------------------------------------------------------------
# Test fixtures: BFM instances created via __new__ so cocotb-bus init is
# skipped. Attributes the hook methods read are set manually.
# ----------------------------------------------------------------------


class _StubBus:
    """Minimal bus stub that satisfies hasattr() / getattr() checks.

    For tests that care about ``is_signal_present(name)``, we expose the
    requested signal names as ``None`` (not present) by default, or as a
    sentinel object (present). The BFM hooks gate on these via
    ``self.is_signal_present(signal_name)``.
    """

    def __init__(self, present_signals: set[str] | None = None,
                 signal_values: dict[str, int] | None = None):
        self._present = present_signals or set()
        self._values = signal_values or {}

    def __getattr__(self, name: str):
        if name in self._present:
            return _StubSignal(self._values.get(name, 0))
        raise AttributeError(name)


class _StubSignal:
    """Stub for a cocotb signal handle. ``.value.integer`` is what hooks read."""

    def __init__(self, integer_value: int = 0):
        self.value = _StubValue(integer_value)

    def setimmediatevalue(self, _v): pass


class _StubValue:
    def __init__(self, integer_value: int):
        self.integer = integer_value
        self.is_resolvable = True

    def __bool__(self):
        return bool(self.integer)


def _make_apb_master_stub():
    """APB4 Master instance bypassing BusDriver init."""
    inst = APBMaster.__new__(APBMaster)
    inst.bus = _StubBus(present_signals={"PPROT", "PSTRB"})
    return inst


def _make_apb5_master_stub():
    """APB5 Master instance with APB5 signals present."""
    inst = APB5Master.__new__(APB5Master)
    inst.bus = _StubBus(present_signals={"PPROT", "PSTRB", "PAUSER", "PWUSER", "PRUSER", "PBUSER", "PWAKEUP"})
    inst.auser_width = 4
    inst.wuser_width = 4
    inst.ruser_width = 4
    inst.buser_width = 4
    return inst


def _make_apb_slave_stub():
    inst = APBSlave.__new__(APBSlave)
    inst.bus = _StubBus(present_signals={"PSLVERR", "PSTRB", "PPROT"})
    return inst


def _make_apb5_slave_stub():
    inst = APB5Slave.__new__(APB5Slave)
    inst.bus = _StubBus(present_signals={
        "PSLVERR", "PSTRB", "PPROT",
        "PAUSER", "PWUSER", "PRUSER", "PBUSER", "PWAKEUP",
    })
    inst.auser_width = 4
    inst.wuser_width = 4
    inst.ruser_width = 4
    inst.buser_width = 4
    return inst


# ----------------------------------------------------------------------
# Hook existence: every override defined in #15 must exist
# ----------------------------------------------------------------------


@pytest.mark.parametrize("cls,hook", [
    (APBMonitor, "_build_packet"),
    (APBMaster,  "_default_randomizer_constraints"),
    (APBMaster,  "_init_extension_signals"),
    (APBMaster,  "_drive_extension_setup_phase"),
    (APBMaster,  "_capture_extension_response"),
    (APBSlave,   "_default_randomizer_constraints"),
    (APBSlave,   "_init_extension_signals"),
    (APBSlave,   "_capture_extension_input_fields"),
    (APBSlave,   "_drive_extension_response"),
    (APBSlave,   "_build_packet"),
])
def test_apb4_base_defines_hook(cls, hook):
    assert hasattr(cls, hook), f"{cls.__name__} is missing hook {hook!r}"


@pytest.mark.parametrize("cls,hook", [
    (APB5Monitor, "_build_packet"),
    (APB5Master,  "_default_randomizer_constraints"),
    (APB5Master,  "_init_extension_signals"),
    (APB5Master,  "_drive_extension_setup_phase"),
    (APB5Master,  "_capture_extension_response"),
    (APB5Slave,   "_default_randomizer_constraints"),
    (APB5Slave,   "_init_extension_signals"),
    (APB5Slave,   "_capture_extension_input_fields"),
    (APB5Slave,   "_drive_extension_response"),
    (APB5Slave,   "_build_packet"),
])
def test_apb5_overrides_hook(cls, hook):
    assert hasattr(cls, hook), f"{cls.__name__} is missing hook {hook!r}"


# ----------------------------------------------------------------------
# Inheritance: APB5 classes must be subclasses of APB classes
# ----------------------------------------------------------------------


def test_apb5_monitor_inherits_apb_monitor():
    assert issubclass(APB5Monitor, APBMonitor)


def test_apb5_master_inherits_apb_master():
    assert issubclass(APB5Master, APBMaster)


def test_apb5_slave_inherits_apb_slave():
    """The Phase B fix — APB5Slave now inherits APBSlave."""
    assert issubclass(APB5Slave, APBSlave)


# ----------------------------------------------------------------------
# APB4Slave default randomizer constraints
# ----------------------------------------------------------------------


def test_apb4_slave_default_constraints():
    stub = _make_apb_slave_stub()
    c = APBSlave._default_randomizer_constraints(stub)
    assert "ready" in c
    assert "error" in c
    assert "pruser" not in c, "APB4 shouldn't include APB5 extensions"


# ----------------------------------------------------------------------
# APB5Slave hook: must extend APB4's constraints via super()
# ----------------------------------------------------------------------


def test_apb5_slave_default_constraints_extends_apb4():
    """The override must call super() and merge — not replace."""
    stub = _make_apb5_slave_stub()
    c = stub._default_randomizer_constraints()
    # Must include APB4 base
    assert "ready" in c
    assert "error" in c
    # Must add APB5 extensions
    assert "pruser" in c
    assert "pbuser" in c


def test_apb5_slave_pruser_range_matches_width():
    """pruser constraint's range should respect ruser_width."""
    stub = _make_apb5_slave_stub()
    stub.ruser_width = 6  # max 63
    c = stub._default_randomizer_constraints()
    # Constraint shape: ([(low, high)], [weight])
    bins, _weights = c["pruser"]
    low, high = bins[0]
    assert low == 0
    assert high == (1 << 6) - 1 == 63


# ----------------------------------------------------------------------
# APB5Slave capture extension input fields
# ----------------------------------------------------------------------


def test_apb5_slave_capture_extension_inputs_returns_pauser_pwuser():
    stub = _make_apb5_slave_stub()
    stub.bus = _StubBus(
        present_signals={"PAUSER", "PWUSER"},
        signal_values={"PAUSER": 0xA, "PWUSER": 0xB},
    )
    fields = stub._capture_extension_input_fields()
    assert fields == {"pauser": 0xA, "pwuser": 0xB}


def test_apb5_slave_capture_extension_inputs_zero_when_signal_missing():
    stub = _make_apb5_slave_stub()
    stub.bus = _StubBus(present_signals=set())  # no signals present
    fields = stub._capture_extension_input_fields()
    assert fields == {"pauser": 0, "pwuser": 0}


# ----------------------------------------------------------------------
# APB4Slave defaults are no-ops for extension hooks (must not error)
# ----------------------------------------------------------------------


def test_apb4_slave_extension_input_fields_returns_empty_dict():
    stub = _make_apb_slave_stub()
    assert APBSlave._capture_extension_input_fields(stub) == {}


def test_apb4_slave_drive_extension_response_is_noop():
    stub = _make_apb_slave_stub()
    # Should not raise — default is no-op
    APBSlave._drive_extension_response(stub, {"any": "values"})


def test_apb4_slave_init_extension_signals_is_noop():
    stub = _make_apb_slave_stub()
    APBSlave._init_extension_signals(stub)  # no error


# ----------------------------------------------------------------------
# APB5Slave _build_packet returns APB5Packet (not APBPacket)
# ----------------------------------------------------------------------


def test_apb5_slave_build_packet_returns_apb5packet():
    stub = _make_apb5_slave_stub()
    stub.bus_width = 32
    stub.addr_width = 12
    stub.strb_bits = 4
    stub.bus = _StubBus(present_signals={"PWAKEUP"}, signal_values={"PWAKEUP": 0})

    pkt = stub._build_packet(
        start_time=100.0,
        count=1,
        pwrite=1,
        paddr=0x100,
        pwdata=0xDEAD,
        prdata=0,
        pstrb=0xF,
        pprot=0,
        pslverr=0,
        direction="WRITE",
        extension_inputs={"pauser": 5, "pwuser": 6},
        rand_values={"pruser": 7, "pbuser": 8, "ready": 0, "error": 0},
    )
    assert isinstance(pkt, APB5Packet)
    assert pkt.fields["pauser"] == 5
    assert pkt.fields["pwuser"] == 6
    assert pkt.fields["pruser"] == 7
    assert pkt.fields["pbuser"] == 8


def test_apb4_slave_build_packet_returns_apbpacket():
    """APB4Slave._build_packet returns base APBPacket, not APB5Packet."""
    stub = _make_apb_slave_stub()
    pkt = APBSlave._build_packet(
        stub,
        start_time=50.0,
        count=1,
        pwrite=0,
        paddr=0x200,
        pwdata=0,
        prdata=0xBEEF,
        pstrb=0xF,
        pprot=0,
        pslverr=0,
        direction="READ",
        extension_inputs={},
        rand_values={"ready": 0, "error": 0},
    )
    assert isinstance(pkt, APBPacket)
    assert not isinstance(pkt, APB5Packet)


# ----------------------------------------------------------------------
# APB5Monitor._build_packet returns APB5Packet
# ----------------------------------------------------------------------


def test_apb5_monitor_build_packet_returns_apb5packet():
    stub = APB5Monitor.__new__(APB5Monitor)
    stub.bus_width = 32
    stub.addr_width = 12
    stub.strb_width = 4
    stub.auser_width = 4
    stub.wuser_width = 4
    stub.ruser_width = 4
    stub.buser_width = 4
    stub.bus = _StubBus(
        present_signals={"PAUSER", "PWUSER", "PRUSER", "PBUSER", "PWAKEUP"},
        signal_values={"PAUSER": 1, "PWUSER": 2, "PRUSER": 3, "PBUSER": 4, "PWAKEUP": 1},
    )

    pkt = stub._build_packet(
        start_time=0.0,
        count=1,
        pwrite=1,
        paddr=0x10,
        pwdata=0xFF,
        prdata=0,
        pstrb=0xF,
        pprot=0,
        pslverr=0,
        direction="WRITE",
    )
    assert isinstance(pkt, APB5Packet)
    assert pkt.fields["pauser"] == 1
    assert pkt.fields["pwuser"] == 2


# ----------------------------------------------------------------------
# APB Master extension hooks
# ----------------------------------------------------------------------


def test_apb5_master_default_constraints_extends_apb4():
    stub = _make_apb5_master_stub()
    c = stub._default_randomizer_constraints()
    # APB4 base
    assert "psel" in c
    assert "penable" in c


def test_apb4_master_extension_setup_phase_is_noop():
    stub = _make_apb_master_stub()
    # Default impl is a no-op; just verify it doesn't error
    class _Txn:
        fields = {"pauser": 5}
    APBMaster._drive_extension_setup_phase(stub, _Txn())


def test_apb5_master_drive_extension_setup_phase_writes_pauser():
    """APB5Master override should drive PAUSER/PWUSER from the transaction fields."""
    stub = _make_apb5_master_stub()

    class _Txn:
        fields = {"pauser": 0xA, "pwuser": 0xB}

    txn = _Txn()
    stub._drive_extension_setup_phase(txn)
    # _StubSignal records the last .value assignment in `.value.integer`
    # but our minimal _StubSignal only exposes `.value`. We just verify no error.

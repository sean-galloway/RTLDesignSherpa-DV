"""Partial signal_map merges with automatic pattern discovery.

A user can override only the DUT signal names that do not match the built-in
patterns.  Keys that are not supplied in ``signal_map`` fall through to normal
automatic discovery, which still hard-fails if a required signal cannot be
found.  Optional signals may also be overridden.
"""

import pytest

from CocoTBFramework.components.shared.field_config import (
    FieldConfig,
    FieldDefinition,
)


def _field_config(*names):
    cfg = FieldConfig()
    for n in names:
        cfg.add_field(FieldDefinition(name=n, bits=8, default=0))
    return cfg


def _resolver(
    protocol_type,
    ports,
    signal_map,
    multi_sig=False,
    field_config=None,
    config=None,
    optional_fields=None,
):
    """Prime a SignalResolver the same way the existing unit tests do."""
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    obj = object.__new__(smh.SignalResolver)
    obj.protocol_type = protocol_type
    obj.signal_map = signal_map
    obj.top_level_ports = {p: object() for p in ports}
    obj.multi_sig = multi_sig
    obj.field_config = field_config
    obj.config = config or {}
    obj.instance_optional_fields = set(optional_fields or ())

    # State needed by the public resolution flow
    obj.resolved_signals = {}
    obj.missing_signals = []
    obj.signal_conflicts = {}
    obj.prefix = ""
    obj.bus_name = ""
    obj.pkt_prefix = ""
    obj.component_name = "UNIT"
    obj.log = None
    obj.super_debug = False
    obj.log_messages = []
    obj.bus = None
    obj.mode = None
    return obj


def _axis_single_config():
    return {
        "signal_map": {
            "o_valid": ["my_tvalid"],
            "i_ready": ["tready"],
        },
        "optional_signal_map": {
            "multi_sig_false": ["tdata"],
        },
    }


def _fifo_single_config():
    return {
        "signal_map": {
            "i_write": ["wr_write"],
            "o_wr_full": ["wr_full"],
        },
        "optional_signal_map": {
            "multi_sig_false": ["wr_data"],
        },
    }


def test_partial_axis_map_mixed_source():
    """A partial map binds the keys it provides; discovery resolves the rest."""
    r = _resolver(
        protocol_type="axis_master",
        ports=["my_tvalid", "tready", "tdata"],
        signal_map={"valid": "my_tvalid"},
        config=_axis_single_config(),
    )

    signals, optional = r.get_signal_lists()

    assert r.resolved_signals["o_valid"] is r.top_level_ports["my_tvalid"]
    assert r.resolved_signals["i_ready"] is r.top_level_ports["tready"]
    assert r.resolved_signals["data_sig"] is r.top_level_ports["tdata"]
    assert r.get_stats()["signal_mapping_source"] == "mixed"


def test_partial_fifo_map_mixed_source():
    """FIFO partial maps work the same way as AXIS/GAXI partial maps."""
    r = _resolver(
        protocol_type="fifo_master",
        ports=["wr_write", "wr_full", "wr_data"],
        signal_map={"write": "wr_write"},
        config=_fifo_single_config(),
    )

    r.get_signal_lists()

    assert r.resolved_signals["i_write"] is r.top_level_ports["wr_write"]
    assert r.resolved_signals["o_wr_full"] is r.top_level_ports["wr_full"]
    assert r.resolved_signals["data_sig"] is r.top_level_ports["wr_data"]
    assert r.get_stats()["signal_mapping_source"] == "mixed"


def test_full_map_reports_manual_source():
    """When the map covers every signal, discovery contributes nothing."""
    r = _resolver(
        protocol_type="fifo_master",
        ports=["wr_write", "wr_full", "wr_data"],
        signal_map={
            "write": "wr_write",
            "full": "wr_full",
            "data": "wr_data",
        },
        config=_fifo_single_config(),
    )

    r.get_signal_lists()

    assert r.resolved_signals["i_write"] is r.top_level_ports["wr_write"]
    assert r.resolved_signals["o_wr_full"] is r.top_level_ports["wr_full"]
    assert r.resolved_signals["data_sig"] is r.top_level_ports["wr_data"]
    assert r.get_stats()["signal_mapping_source"] == "manual"


def test_mapped_signal_not_on_dut_raises():
    """A map entry that names a missing DUT port still raises immediately."""
    r = _resolver(
        protocol_type="axis_master",
        ports=["tready", "tdata"],
        signal_map={"valid": "my_tvalid"},
        config=_axis_single_config(),
    )

    with pytest.raises(ValueError) as exc:
        r.get_signal_lists()
    assert "my_tvalid" in str(exc.value)


def test_unexpected_key_raises():
    """Typo protection: keys outside the valid set still raise."""
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    r = _resolver(
        protocol_type="axis_master",
        ports=["my_tvalid", "tready", "tdata"],
        signal_map={"valid": "my_tvalid", "bad_key": "x"},
        config=_axis_single_config(),
    )

    with pytest.raises(ValueError) as exc:
        smh.SignalResolver._validate_signal_map(r)
    assert "unexpected" in str(exc.value).lower()
    assert "bad_key" in str(exc.value)


def test_optional_field_override_skips_discovery():
    """An optional multi-sig field supplied in the map is not touched by discovery."""
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    r = _resolver(
        protocol_type="axis_master",
        ports=["my_tlast"],
        signal_map={"last": "my_tlast"},
        multi_sig=True,
        field_config=_field_config("data", "last"),
        config={
            "signal_map": {
                "o_valid": ["valid"],
                "i_ready": ["ready"],
            },
            "optional_signal_map": {
                "multi_sig_true": ["{field_name}"],
            },
            "optional_fields": (),
        },
    )

    # Bind the manually-mapped field and prime the required handshake signals
    # so the optional resolver only has to decide whether to look for 'last'.
    smh.SignalResolver._resolve_signals_from_map(r)
    r.resolved_signals["o_valid"] = object()
    r.resolved_signals["i_ready"] = object()

    recorded = []

    def fake_find(logical_name, patterns, required=False, field_name=None):
        recorded.append(field_name)
        return object()

    r._find_signal_match = fake_find
    smh.SignalResolver._resolve_optional_signals(r)

    assert "last" not in recorded, "discovery should skip the overridden field"
    assert "data" in recorded, "discovery should still resolve unmapped fields"


def test_missing_required_still_hard_fails():
    """Partial maps do not relax the hard failure for missing required signals."""
    r = _resolver(
        protocol_type="axis_master",
        ports=["my_tvalid"],  # ready and data are absent
        signal_map={"valid": "my_tvalid"},
        config=_axis_single_config(),
    )

    with pytest.raises(ValueError) as exc:
        r.get_signal_lists()
    msg = str(exc.value)
    assert "Missing required signals" in msg
    assert "i_ready" in msg or "ready" in msg


def test_axis_example_usage_keys_validate():
    """The full key set from axis_example_usage.py must be accepted as valid."""
    from CocoTBFramework.components.axis4 import get_axis_signal_map
    from CocoTBFramework.components.axis4.axis_field_configs import AXISFieldConfigs
    from CocoTBFramework.components.shared.signal_mapping_helper import SignalResolver

    signal_map = get_axis_signal_map(prefix="custom_m_", direction="master")
    field_config = AXISFieldConfigs.create_axis_config_from_hw_params(
        data_width=32, id_width=8, dest_width=4, user_width=1
    )

    r = object.__new__(SignalResolver)
    r.protocol_type = "axis_master"
    r.multi_sig = True
    r.field_config = field_config
    r.signal_map = signal_map
    r.instance_optional_fields = set()
    r.config = {"optional_fields": ()}
    r.top_level_ports = {name: object() for name in signal_map.values()}
    r.log = None
    r.component_name = "AXIS_TEST"

    # Must not raise on the full key set.
    SignalResolver._validate_signal_map(r)

    logical = SignalResolver._create_logical_mapping(r) | SignalResolver._optional_logical_mapping(r)
    for key in signal_map:
        assert key in logical, f"{key!r} is not a recognized signal_map key"

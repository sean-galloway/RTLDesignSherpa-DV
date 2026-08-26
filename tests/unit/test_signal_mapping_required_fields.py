"""A field declared in field_config must bind to a signal.

Treating an unbindable field as optional is how a testbench stops being
able to fail. The component logs a warning, leaves the field unresolved,
and every read returns 0: data comparisons pass against 0x0, LAST reads
False forever, and the suite goes green over a DUT nobody is checking.

That is not a hypothetical. The converters' width primitives ran that way
across 22 configurations because the TB passed `prefix="wide_"` together
with `pkt_prefix="wide"`, so the resolver looked for `wide_wide_data`
while the port was `wide_data`. `valid` and `ready` bound correctly, so
traffic flowed and the tests looked alive.

Fields that a given DUT genuinely does not carry opt out by name through
`optional_fields`.
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


def _resolver(monkeypatch, ports, field_names, optional_fields=None):
    """A SignalResolver primed with a fixed set of top-level ports."""
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    cls = smh.SignalResolver
    obj = object.__new__(cls)
    obj.top_level_ports = {p: object() for p in ports}
    obj.field_config = _field_config(*field_names)
    obj.multi_sig = True
    obj.missing_signals = []
    obj.resolved_signals = {}
    obj.signal_conflicts = []
    obj.super_debug = False
    obj.component_name = "UNIT"
    obj.prefix = ""
    obj.log = None
    obj.config = {"optional_fields": tuple(optional_fields or ())}
    obj.instance_optional_fields = set()
    return obj


def test_instance_optional_fields_union(monkeypatch):
    """Per-instance optional_fields union with the config-level set.

    An AXI5 DUT has no AxREGION port (AMBA5 removed it); the TB opts the
    field out per instance without weakening the config for AXI4 DUTs.
    """
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    r = _resolver(monkeypatch, ["data"], ["data", "region"])
    r.instance_optional_fields = {"region"}
    recorded = {}

    def fake_find(logical_name, patterns, required=False, field_name=None):
        recorded[field_name] = required
        return None

    r._find_signal_match = fake_find
    r.config["optional_signal_map"] = {"multi_sig_true": ["{field_name}"]}
    smh.SignalResolver._resolve_optional_signals(r)

    assert recorded.get("data") is True, "data should still be required"
    assert recorded.get("region") is False, "instance opt-out ignored"


def test_declared_field_is_required_not_optional(monkeypatch):
    """The core contract: a declared field records itself as REQUIRED.

    `required` is what routes a miss into validation instead of a warning,
    so this is the flag that decides whether a broken TB can pass.
    """
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    r = _resolver(monkeypatch, ["wide_data"], ["data", "last"])
    recorded = []

    def fake_find(logical_name, patterns, required=False, field_name=None):
        recorded.append((field_name, required))
        return None

    r._find_signal_match = fake_find
    r.config["optional_signal_map"] = {"multi_sig_true": ["{field_name}"]}
    smh.SignalResolver._resolve_optional_signals(r)

    assert recorded, "no fields were resolved"
    assert all(req for _, req in recorded), (
        f"declared fields resolved as optional: {recorded}"
    )


def test_optional_fields_opt_out(monkeypatch):
    """A field the DUT genuinely lacks can still be declared optional."""
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    r = _resolver(monkeypatch, ["data"], ["data", "user"],
                  optional_fields=("user",))
    recorded = {}

    def fake_find(logical_name, patterns, required=False, field_name=None):
        recorded[field_name] = required
        return None

    r._find_signal_match = fake_find
    r.config["optional_signal_map"] = {"multi_sig_true": ["{field_name}"]}
    smh.SignalResolver._resolve_optional_signals(r)

    assert recorded.get("data") is True, "data should still be required"
    assert recorded.get("user") is False, "user opted out but stayed required"


def test_missing_required_field_reports_what_it_tried():
    """The error has to name the field and the names it looked for.

    A bare 'signal not found' sends the reader to the wrong place; the
    doubled-prefix bug was diagnosable only because the message listed
    `wide_wide_data` against a port list containing `wide_data`.
    """
    from CocoTBFramework.components.shared import signal_mapping_helper as smh

    r = object.__new__(smh.SignalResolver)
    r.component_name = "WIDE_OUT"
    r.missing_signals = [("field_data_sig", ["wide_wide_data"], True)]
    r.top_level_ports = {"wide_data": object(), "wide_valid": object()}
    r.resolved_signals = {}
    r.signal_conflicts = []
    r.multi_sig = True
    r.log = None

    with pytest.raises(Exception) as exc:
        smh.SignalResolver._validate_required_signals(r)
    msg = str(exc.value)
    assert "field_data_sig" in msg
    assert "wide_wide_data" in msg, "should show what it tried"
    assert "wide_data" in msg, "should show what was available"

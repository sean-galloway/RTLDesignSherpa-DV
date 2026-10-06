# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: test_ace_signal_map
# Purpose: AXI4-ACE channel identifiers resolve through the shared signal mapper
#
# Subsystem: framework

"""AXI4-ACE signal patterns resolve representative DUT port names.

ACE adds three snoop channels (AC/CR/CD) and an ARSNOOP/AWSNOOP qualifier to
the AXI4 address channels. This test pins the shared protocol-pattern layer:
every new identifier is accepted by ``protocol_types`` and registered in
``signal_mapping_helper.PROTOCOL_SIGNAL_CONFIGS``, and the patterns find the
ACE-specific signals under the m_axi_/s_axi_/fub_axi_/fub_/plain naming
conventions used by the RTL.
"""

import pytest

from CocoTBFramework.components.shared.field_config import (
    FieldConfig,
    FieldDefinition,
)
from CocoTBFramework.components.shared.protocol_types import (
    PROTOCOL_TYPES,
    validate_protocol_type,
)
from CocoTBFramework.components.shared.signal_mapping_helper import (
    PROTOCOL_SIGNAL_CONFIGS,
    SignalResolver,
)

ACE_PROTOCOLS = [
    "axi4ace_ar_master", "axi4ace_aw_master", "axi4ace_w_master",
    "axi4ace_r_slave",   "axi4ace_b_slave",
    "axi4ace_ac_master", "axi4ace_ac_slave",
    "axi4ace_cr_master", "axi4ace_cr_slave",
    "axi4ace_cd_master", "axi4ace_cd_slave",
]

CHANNEL_FIELDS = {
    "ar": ["id", "addr", "len", "size", "burst", "lock", "cache",
           "prot", "qos", "region", "user", "snoop"],
    "aw": ["id", "addr", "len", "size", "burst", "lock", "cache",
           "prot", "qos", "region", "user", "snoop"],
    "w":  ["data", "strb", "last", "user"],
    "r":  ["id", "data", "resp", "last", "user"],
    "b":  ["id", "resp", "user"],
    "ac": ["addr", "snoop", "prot"],
    "cr": ["resp"],
    "cd": ["data", "last"],
}


def _field_config(*names):
    cfg = FieldConfig()
    for n in names:
        cfg.add_field(FieldDefinition(name=n, bits=8, default=0))
    return cfg


def _channel_from_protocol(protocol_type):
    """Return the channel suffix for an ACE protocol identifier."""
    return protocol_type.split("_")[1]


def _resolver(protocol_type, ports, prefix="", bus_name="", pkt_prefix=""):
    """Prime a SignalResolver the same way the existing unit tests do."""
    obj = object.__new__(SignalResolver)
    obj.protocol_type = protocol_type
    obj.signal_map = None
    obj.top_level_ports = {p: object() for p in ports}
    obj.multi_sig = True
    obj.field_config = _field_config(*CHANNEL_FIELDS[_channel_from_protocol(protocol_type)])
    obj.config = PROTOCOL_SIGNAL_CONFIGS[protocol_type]
    obj.instance_optional_fields = set()

    # State needed by the public resolution flow
    obj.resolved_signals = {}
    obj.missing_signals = []
    obj.signal_conflicts = {}
    obj.prefix = prefix
    obj.bus_name = bus_name
    obj.pkt_prefix = pkt_prefix
    obj.component_name = "ACE_UNIT"
    obj.log = None
    obj.super_debug = False
    obj.log_messages = []
    obj.bus = None
    obj.mode = None
    return obj


def _ace_ports(channel, base):
    """Build a DUT port list for an ACE channel using the given base name.

    ``base`` is the channel prefix exactly as it appears in the RTL, e.g.
    ``m_axi_ar`` or ``fub_axi_ar`` or ``fub_ac``.
    """
    valid = f"{base}valid"
    ready = f"{base}ready"
    fields = CHANNEL_FIELDS[channel]
    return [valid, ready] + [f"{base}{f}" for f in fields]


@pytest.mark.parametrize("protocol_type", ACE_PROTOCOLS)
def test_ace_protocol_type_is_registered(protocol_type):
    """Every ACE identifier is accepted by the canonical type registry."""
    assert protocol_type in PROTOCOL_TYPES
    assert protocol_type in PROTOCOL_SIGNAL_CONFIGS
    validate_protocol_type(protocol_type)


@pytest.mark.parametrize("protocol_type", ACE_PROTOCOLS)
def test_ace_protocol_config_declares_optional_fields(protocol_type):
    """Each ACE channel config carries an optional_fields entry.

    The entry existing is what makes qualifier omission survivable without a
    per-call-site opt-out.
    """
    assert "optional_fields" in PROTOCOL_SIGNAL_CONFIGS[protocol_type]


@pytest.mark.parametrize("protocol_type", ACE_PROTOCOLS)
def test_ace_protocol_resolves_m_axi_ports(protocol_type):
    """Patterns resolve against the manager-side m_axi_ prefix."""
    channel = _channel_from_protocol(protocol_type)
    base = f"m_axi_{channel}"
    ports = _ace_ports(channel, base)
    r = _resolver(protocol_type, ports, prefix="m_axi_")
    r.get_signal_lists()

    for field in CHANNEL_FIELDS[channel]:
        logical = f"field_{field}_sig"
        assert logical in r.resolved_signals, (
            f"{protocol_type}: {logical} not resolved; "
            f"resolved={sorted(r.resolved_signals)}"
        )
        assert r.resolved_signals[logical] is not None


@pytest.mark.parametrize("protocol_type", ACE_PROTOCOLS)
def test_ace_protocol_resolves_s_axi_ports(protocol_type):
    """Patterns resolve against the subordinate-side s_axi_ prefix."""
    channel = _channel_from_protocol(protocol_type)
    base = f"s_axi_{channel}"
    ports = _ace_ports(channel, base)
    r = _resolver(protocol_type, ports, prefix="s_axi_")
    r.get_signal_lists()

    for field in CHANNEL_FIELDS[channel]:
        logical = f"field_{field}_sig"
        assert logical in r.resolved_signals
        assert r.resolved_signals[logical] is not None


@pytest.mark.parametrize("protocol_type", ACE_PROTOCOLS)
def test_ace_protocol_resolves_plain_ports(protocol_type):
    """Patterns resolve when no AXI prefix is present."""
    channel = _channel_from_protocol(protocol_type)
    base = channel
    ports = _ace_ports(channel, base)
    r = _resolver(protocol_type, ports)
    r.get_signal_lists()

    for field in CHANNEL_FIELDS[channel]:
        logical = f"field_{field}_sig"
        assert logical in r.resolved_signals
        assert r.resolved_signals[logical] is not None


@pytest.mark.parametrize("base", ["m_axi_ar", "s_axi_ar", "fub_axi_ar", "ar"])
def test_arsnoop_resolves_in_ar_master(base):
    """The ACE AR channel carries the extra snoop qualifier."""
    prefix = ""
    bus_name = ""
    if base == "m_axi_ar":
        prefix = "m_axi_"
    elif base == "s_axi_ar":
        prefix = "s_axi_"
    elif base == "fub_axi_ar":
        prefix = "fub_axi_"

    ports = _ace_ports("ar", base)
    r = _resolver("axi4ace_ar_master", ports, prefix=prefix, bus_name=bus_name)
    r.get_signal_lists()
    assert r.resolved_signals["field_snoop_sig"] is r.top_level_ports[f"{base}snoop"]


@pytest.mark.parametrize("base", ["m_axi_aw", "s_axi_aw", "fub_axi_aw", "aw"])
def test_awsnoop_resolves_in_aw_master(base):
    """The ACE AW channel carries the extra snoop qualifier."""
    prefix = ""
    if base == "m_axi_aw":
        prefix = "m_axi_"
    elif base == "s_axi_aw":
        prefix = "s_axi_"
    elif base == "fub_axi_aw":
        prefix = "fub_axi_"

    ports = _ace_ports("aw", base)
    r = _resolver("axi4ace_aw_master", ports, prefix=prefix)
    r.get_signal_lists()
    assert r.resolved_signals["field_snoop_sig"] is r.top_level_ports[f"{base}snoop"]


@pytest.mark.parametrize("base", ["m_axi_ac", "s_axi_ac", "fub_ac", "ac"])
def test_ac_fields_resolve(base):
    """The ACE AC channel fields resolve for all naming conventions."""
    prefix = ""
    if base.startswith("m_axi_"):
        prefix = "m_axi_"
    elif base.startswith("s_axi_"):
        prefix = "s_axi_"
    elif base.startswith("fub_"):
        prefix = "fub_"

    ports = _ace_ports("ac", base)
    for role in ("master", "slave"):
        r = _resolver(f"axi4ace_ac_{role}", ports, prefix=prefix)
        r.get_signal_lists()
        assert r.resolved_signals["field_addr_sig"] is r.top_level_ports[f"{base}addr"]
        assert r.resolved_signals["field_snoop_sig"] is r.top_level_ports[f"{base}snoop"]
        assert r.resolved_signals["field_prot_sig"] is r.top_level_ports[f"{base}prot"]


@pytest.mark.parametrize("base", ["m_axi_cr", "s_axi_cr", "fub_cr", "cr"])
def test_cr_fields_resolve(base):
    """The ACE CR channel fields resolve for all naming conventions."""
    prefix = ""
    if base.startswith("m_axi_"):
        prefix = "m_axi_"
    elif base.startswith("s_axi_"):
        prefix = "s_axi_"
    elif base.startswith("fub_"):
        prefix = "fub_"

    ports = _ace_ports("cr", base)
    for role in ("master", "slave"):
        r = _resolver(f"axi4ace_cr_{role}", ports, prefix=prefix)
        r.get_signal_lists()
        assert r.resolved_signals["field_resp_sig"] is r.top_level_ports[f"{base}resp"]


@pytest.mark.parametrize("base", ["m_axi_cd", "s_axi_cd", "fub_cd", "cd"])
def test_cd_fields_resolve(base):
    """The ACE CD channel fields resolve for all naming conventions."""
    prefix = ""
    if base.startswith("m_axi_"):
        prefix = "m_axi_"
    elif base.startswith("s_axi_"):
        prefix = "s_axi_"
    elif base.startswith("fub_"):
        prefix = "fub_"

    ports = _ace_ports("cd", base)
    for role in ("master", "slave"):
        r = _resolver(f"axi4ace_cd_{role}", ports, prefix=prefix)
        r.get_signal_lists()
        assert r.resolved_signals["field_data_sig"] is r.top_level_ports[f"{base}data"]
        assert r.resolved_signals["field_last_sig"] is r.top_level_ports[f"{base}last"]

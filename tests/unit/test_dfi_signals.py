"""Unit tests for the DFI signal envelope (issue #16)."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_signals import (
    SUPPORTED_MEMORY_BY_VERSION,
    DFIVersion,
    MemoryType,
    SignalDirection,
    SignalSpec,
    SubInterface,
    MVP_MEMORY_TYPES,
    MVP_SUB_INTERFACES,
    MVP_VERSIONS,
    is_supported_pair,
    optional_signal_names,
    required_signal_names,
    signals_for,
    validate_configuration,
)


# ---------------------------------------------------------------------
# MVP envelope
# ---------------------------------------------------------------------


def test_mvp_versions_is_v21_only():
    assert MVP_VERSIONS == frozenset({DFIVersion.V2_1})


def test_mvp_memory_types_excludes_ddr4_and_lpddr4_plus():
    """Phase 2 will add these — they should NOT be in the MVP set."""
    assert MemoryType.DDR4 not in MVP_MEMORY_TYPES
    assert MemoryType.DDR5 not in MVP_MEMORY_TYPES
    assert MemoryType.LPDDR3 not in MVP_MEMORY_TYPES
    assert MemoryType.LPDDR4 not in MVP_MEMORY_TYPES
    assert MemoryType.LPDDR5 not in MVP_MEMORY_TYPES


def test_mvp_sub_interfaces_is_command_write_read_only():
    assert MVP_SUB_INTERFACES == frozenset({
        SubInterface.COMMAND,
        SubInterface.WRITE_DATA,
        SubInterface.READ_DATA,
    })


# ---------------------------------------------------------------------
# Signal gating by memory type (matches DFI v2.1 Tables 2/4/6)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("memory_type", [
    MemoryType.DDR1, MemoryType.LPDDR1, MemoryType.DDR2,
    MemoryType.DDR3, MemoryType.LPDDR2,
])
def test_universal_signals_present_for_all_memory_types(memory_type):
    """address, cke, cs_n, wrdata, rddata family — always there."""
    names = {s.name for s in signals_for(DFIVersion.V2_1, memory_type)}
    for required in ("address", "cke", "cs_n", "wrdata", "wrdata_en",
                     "wrdata_mask", "rddata", "rddata_en", "rddata_valid"):
        assert required in names, (
            f"{required} should be universal but missing for {memory_type.value}"
        )


def test_reset_n_only_on_ddr3():
    """dfi_reset_n is DDR3-only per Table 2."""
    for m in (MemoryType.DDR1, MemoryType.DDR2, MemoryType.LPDDR1, MemoryType.LPDDR2):
        names = {s.name for s in signals_for(DFIVersion.V2_1, m)}
        assert "reset_n" not in names, f"reset_n should not appear for {m.value}"

    names_ddr3 = {s.name for s in signals_for(DFIVersion.V2_1, MemoryType.DDR3)}
    assert "reset_n" in names_ddr3


def test_odt_only_on_ddr2_and_ddr3():
    """dfi_odt is DDR2+DDR3 only per Table 2."""
    for m in (MemoryType.DDR1, MemoryType.LPDDR1, MemoryType.LPDDR2):
        names = {s.name for s in signals_for(DFIVersion.V2_1, m)}
        assert "odt" not in names, f"odt should not appear for {m.value}"

    for m in (MemoryType.DDR2, MemoryType.DDR3):
        names = {s.name for s in signals_for(DFIVersion.V2_1, m)}
        assert "odt" in names, f"odt should appear for {m.value}"


def test_lpddr2_idles_ddr_command_signals():
    """LPDDR2 doesn't use bank/ras_n/cas_n/we_n (held idle per spec §3.1)."""
    names = {s.name for s in signals_for(DFIVersion.V2_1, MemoryType.LPDDR2)}
    for idled in ("bank", "ras_n", "cas_n", "we_n"):
        assert idled not in names, (
            f"{idled} should not appear in LPDDR2 envelope (it's held idle)"
        )


def test_rddata_dnv_only_on_lpddr2():
    """dfi_rddata_dnv is LPDDR2-only per Table 6."""
    for m in (MemoryType.DDR1, MemoryType.DDR2, MemoryType.DDR3,
              MemoryType.LPDDR1):
        names = {s.name for s in signals_for(DFIVersion.V2_1, m)}
        assert "rddata_dnv" not in names

    names = {s.name for s in signals_for(DFIVersion.V2_1, MemoryType.LPDDR2)}
    assert "rddata_dnv" in names


# ---------------------------------------------------------------------
# Sub-interface profile selection
# ---------------------------------------------------------------------


def test_command_only_profile_excludes_data_signals():
    sigs = signals_for(
        DFIVersion.V2_1, MemoryType.DDR3,
        sub_interfaces=frozenset({SubInterface.COMMAND}),
    )
    names = {s.name for s in sigs}
    assert "address" in names
    assert "wrdata" not in names
    assert "rddata" not in names


def test_read_only_profile_has_only_read_signals():
    sigs = signals_for(
        DFIVersion.V2_1, MemoryType.DDR3,
        sub_interfaces=frozenset({SubInterface.READ_DATA}),
    )
    names = {s.name for s in sigs}
    assert names == {"rddata", "rddata_en", "rddata_valid"}


# ---------------------------------------------------------------------
# Signal name helpers (for cocotb_bus._signals / _optional_signals)
# ---------------------------------------------------------------------


def test_required_names_use_dfi_prefix():
    names = required_signal_names(DFIVersion.V2_1, MemoryType.DDR3)
    for name in names:
        assert name.startswith("dfi_")


def test_required_names_custom_prefix():
    names = required_signal_names(DFIVersion.V2_1, MemoryType.DDR3,
                                   prefix="ch0_dfi")
    assert all(n.startswith("ch0_dfi_") for n in names)


def test_required_holds_universal_signals_only():
    """Universal signals → _signals; memory-gated → _optional_signals."""
    req = set(required_signal_names(DFIVersion.V2_1, MemoryType.DDR3))
    opt = set(optional_signal_names(DFIVersion.V2_1, MemoryType.DDR3))
    # No overlap
    assert req.isdisjoint(opt)
    # Universal-only sample
    assert "dfi_address" in req
    assert "dfi_cke" in req
    # Memory-gated sample
    assert "dfi_odt" in opt    # DDR2/DDR3
    assert "dfi_reset_n" in opt  # DDR3


# ---------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------


def test_rddata_is_phy_to_mc():
    sigs = {s.name: s for s in signals_for(DFIVersion.V2_1, MemoryType.DDR3)}
    assert sigs["rddata"].direction == SignalDirection.PHY_TO_MC
    assert sigs["rddata_valid"].direction == SignalDirection.PHY_TO_MC


def test_rddata_en_is_mc_to_phy():
    sigs = {s.name: s for s in signals_for(DFIVersion.V2_1, MemoryType.DDR3)}
    # rddata_en is from MC even though it belongs to the read-data interface
    assert sigs["rddata_en"].direction == SignalDirection.MC_TO_PHY


def test_all_command_signals_are_mc_to_phy():
    sigs = signals_for(
        DFIVersion.V2_1, MemoryType.DDR3,
        sub_interfaces=frozenset({SubInterface.COMMAND}),
    )
    assert all(s.direction == SignalDirection.MC_TO_PHY for s in sigs)


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


def test_validate_accepts_mvp_combo():
    validate_configuration(
        DFIVersion.V2_1, MemoryType.DDR3, MVP_SUB_INTERFACES,
    )  # no raise


def test_validate_rejects_post_mvp_version():
    with pytest.raises(ValueError, match="Phase 2"):
        validate_configuration(
            DFIVersion.V5_2, MemoryType.DDR3, MVP_SUB_INTERFACES,
        )


def test_validate_rejects_post_mvp_memory_type():
    with pytest.raises(ValueError, match="Phase 2"):
        validate_configuration(
            DFIVersion.V2_1, MemoryType.DDR5, MVP_SUB_INTERFACES,
        )


def test_validate_rejects_phase2_sub_interface():
    with pytest.raises(ValueError, match="Phase 2"):
        validate_configuration(
            DFIVersion.V2_1, MemoryType.DDR3,
            MVP_SUB_INTERFACES | {SubInterface.TRAINING},
        )


# ---------------------------------------------------------------------
# Per-version memory support matrix (SUPPORTED_MEMORY_BY_VERSION)
# ---------------------------------------------------------------------


def test_v2_1_doesnt_have_ddr4():
    """DDR4 was added in v3.0."""
    assert MemoryType.DDR4 not in SUPPORTED_MEMORY_BY_VERSION[DFIVersion.V2_1]


def test_v3_1_adds_ddr4_and_lpddr3():
    v3_support = SUPPORTED_MEMORY_BY_VERSION[DFIVersion.V3_1]
    assert MemoryType.DDR4 in v3_support
    assert MemoryType.LPDDR3 in v3_support
    # Still has v2.1 legacy
    assert MemoryType.DDR3 in v3_support


def test_v4_0_adds_lpddr4():
    assert MemoryType.LPDDR4 in SUPPORTED_MEMORY_BY_VERSION[DFIVersion.V4_0]


def test_v5_2_adds_ddr5_lpddr5_keeps_legacy():
    v5_support = SUPPORTED_MEMORY_BY_VERSION[DFIVersion.V5_2]
    assert MemoryType.DDR5 in v5_support
    assert MemoryType.LPDDR5 in v5_support
    # Legacy still supported in v5.x
    assert MemoryType.DDR3 in v5_support


def test_is_supported_pair_matches_matrix():
    assert is_supported_pair(DFIVersion.V2_1, MemoryType.DDR3)
    assert not is_supported_pair(DFIVersion.V2_1, MemoryType.DDR5)
    assert is_supported_pair(DFIVersion.V5_2, MemoryType.DDR5)


def test_validate_catches_legacy_only_pair_at_higher_version(monkeypatch):
    """Even after widening MVP to a higher version + DDR5, the
    (version, memory) check still resolves pairs against the spec
    matrix. Picks v3.1+DDR5 (DDR5 wasn't added until v5.x).
    """
    monkeypatch.setattr(
        "CocoTBFramework.components.dfi.dfi_signals.MVP_VERSIONS",
        frozenset({DFIVersion.V2_1, DFIVersion.V3_1}),
    )
    monkeypatch.setattr(
        "CocoTBFramework.components.dfi.dfi_signals.MVP_MEMORY_TYPES",
        MVP_MEMORY_TYPES | {MemoryType.DDR5},
    )
    with pytest.raises(ValueError, match="does not support"):
        validate_configuration(
            DFIVersion.V3_1, MemoryType.DDR5, MVP_SUB_INTERFACES,
        )


# ---------------------------------------------------------------------
# SignalSpec.max_version + applies()
# ---------------------------------------------------------------------


def test_signal_spec_max_version_defaults_to_none():
    """Default ``max_version`` means signal stays in current spec."""
    spec = SignalSpec(
        name="x",
        direction=SignalDirection.MC_TO_PHY,
        width_key="data_width",
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        memory_types=frozenset(),
        description="test",
    )
    assert spec.max_version is None


def test_applies_rejects_when_above_max_version():
    """If a signal is retired before v5.2, ``max_version=V4_0`` excludes v5.2."""
    spec = SignalSpec(
        name="legacy",
        direction=SignalDirection.MC_TO_PHY,
        width_key="data_width",
        sub_interface=SubInterface.COMMAND,
        min_version=DFIVersion.V2_1,
        max_version=DFIVersion.V4_0,
        memory_types=frozenset(),
        description="test",
    )
    # Within range
    assert spec.applies(DFIVersion.V2_1, MemoryType.DDR3)
    assert spec.applies(DFIVersion.V4_0, MemoryType.DDR3)
    # Beyond max
    assert not spec.applies(DFIVersion.V5_2, MemoryType.DDR3)


# ---------------------------------------------------------------------
# Expanded SubInterface + MemoryType enums
# ---------------------------------------------------------------------


def test_sub_interface_enum_covers_v5_interfaces():
    """v5.x §3 enumerates the sub-interfaces below (plus TRAINING).
    The enum should have all of them."""
    expected = {
        SubInterface.COMMAND, SubInterface.WRITE_DATA, SubInterface.READ_DATA,
        SubInterface.WCK_CONTROL, SubInterface.STATUS, SubInterface.LOW_POWER,
        SubInterface.UPDATE, SubInterface.PHY_MANAGED,
        SubInterface.MC_TO_PHY_MSG, SubInterface.PHY_ERROR,
        SubInterface.DBI, SubInterface.ECC, SubInterface.LINK_CRC,
        SubInterface.MULTI_CHANNEL,
        SubInterface.TRAINING,
    }
    assert set(SubInterface) == expected


def test_memory_type_enum_covers_v5_scope():
    """Scope: DDR1-5 + LPDDR1-5. v6+ types (LPDDR6, HBM4) are out of scope."""
    assert MemoryType.DDR5 in set(MemoryType)
    assert MemoryType.LPDDR5 in set(MemoryType)
    # Forward-looking types should NOT be in the enum at this scope.
    assert not hasattr(MemoryType, "LPDDR6")
    assert not hasattr(MemoryType, "HBM4")


def test_control_enum_value_renamed_to_command():
    """Later DFI revisions call this the "Command Interface"; we use that name."""
    assert SubInterface.COMMAND.value == "command"
    assert not hasattr(SubInterface, "CONTROL")

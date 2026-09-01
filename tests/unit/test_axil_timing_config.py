# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: test_axil_timing_config
# Purpose: The Lite timing profiles constrain every channel, not just reads
#
# Subsystem: framework

"""AXI4-Lite / AXI5-Lite timing profiles.

The check that earns its keep here is channel COVERAGE. ``axi4_timing_config``
constrains only ``ar_*``/``r_*``, yet ``axi4_master_write_tb`` imports it -- so
a write testbench asking for 'axi4_slow' silently gets default timing on AW, W
and B and nobody notices, because a missing constraint does not raise, it just
does not slow anything down. ``axi5_timing_config`` constrains all five. The
Lite modules follow AXI5, and this test is what stops them drifting back.
"""
import pytest

from CocoTBFramework.components.axil4.axil4_timing_config import (
    create_axil4_randomizer_configs,
    create_axil4_timing_from_profile,
    get_axil4_timing_profiles,
)
from CocoTBFramework.components.axil5.axil5_timing_config import (
    create_axil5_randomizer_configs,
    create_axil5_timing_from_profile,
    get_axil5_timing_profiles,
    get_timing_for_axil5_feature,
)

ALL_DELAY_KEYS = {
    'aw_valid_delay', 'aw_ready_delay',
    'w_valid_delay', 'w_ready_delay',
    'b_valid_delay', 'b_ready_delay',
    'ar_valid_delay', 'ar_ready_delay',
    'r_valid_delay', 'r_ready_delay',
}

FAMILIES = (
    ('axil4', get_axil4_timing_profiles, create_axil4_timing_from_profile,
     create_axil4_randomizer_configs),
    ('axil5', get_axil5_timing_profiles, create_axil5_timing_from_profile,
     create_axil5_randomizer_configs),
)


@pytest.mark.parametrize("fam,profiles,create,_configs", FAMILIES)
def test_every_profile_constrains_all_five_channels(fam, profiles, create, _configs):
    """This is the AXI4 gap, kept out of the Lite families."""
    for name in profiles():
        got = set(create(name)['constraints'])
        assert got == ALL_DELAY_KEYS, (
            f"{name} constrains {sorted(got)}; a channel missing here is not "
            f"an error at runtime, it is silently un-delayed traffic"
        )


@pytest.mark.parametrize("fam,profiles,create,_configs", FAMILIES)
def test_profile_names_are_family_prefixed(fam, profiles, create, _configs):
    assert profiles(), f"{fam} exposes no profiles"
    for name in profiles():
        assert name.startswith(fam + '_'), name


@pytest.mark.parametrize("fam,profiles,create,_configs", FAMILIES)
def test_unknown_profile_falls_back_but_reports_what_was_asked(fam, profiles, create, _configs):
    """Silent fallback is the AXI4/AXI5 behaviour and is kept, but the result
    carries the name the caller ASKED for -- so a typo is discoverable rather
    than looking like a successful 'normal' run."""
    cfg = create(f'{fam}_no_such_profile')
    assert cfg['profile_name'] == f'{fam}_no_such_profile'
    assert cfg['constraints'] == create(f'{fam}_normal')['constraints']


@pytest.mark.parametrize("fam,profiles,create,configs", FAMILIES)
def test_randomizer_configs_cover_every_profile(fam, profiles, create, configs):
    short = {n.split('_', 1)[1] for n in profiles()}
    assert set(configs()) == short


def test_axil5_adds_secure_and_only_secure():
    """AXI5 has atomic/mte/chunked profiles too. AXI5-Lite has none of those
    features, so inventing profiles for them would be fiction."""
    extra = set(get_axil5_timing_profiles()) - {
        n.replace('axil4', 'axil5') for n in get_axil4_timing_profiles()
    }
    assert extra == {'axil5_secure'}


@pytest.mark.parametrize("feature", ['secure', 'nsaid', 'mpam', 'mecid'])
def test_axil5_feature_mapping_hits_the_secure_profile(feature):
    assert get_timing_for_axil5_feature(feature)['profile_name'] == 'axil5_secure'


@pytest.mark.parametrize("feature", ['atomic', 'mte', 'chunked'])
def test_axil5_features_that_do_not_exist_fall_back(feature):
    """Not a mapping gap: AXI5-Lite has no atomics, no tagging, no chunking."""
    assert get_timing_for_axil5_feature(feature)['profile_name'] == 'axil5_normal'

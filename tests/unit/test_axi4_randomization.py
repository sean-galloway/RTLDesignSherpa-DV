"""Unit tests for AXI4/AXI5 randomization infrastructure.

Covers the repaired axi4_randomization_manager (previously unimportable) and
the randomize_fields() supported-field fix in axi4_randomization_config /
axi5_randomization_config: signal-style field names ('awaddr', 'arlen', ...)
must produce real values instead of "Unsupported field" warnings.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.axi4.axi4_randomization_config import (
    AXI4RandomizationConfig,
    AXI4RandomizationProfile,
)
from CocoTBFramework.components.axi4.axi4_randomization_manager import (
    AXI4RandomizationManager,
    AXI4TimingConfig,
    create_axi4_timing_config,
    create_compliance_randomization,
    create_error_injection_randomization,
    create_performance_randomization,
    create_unified_randomization,
)
from CocoTBFramework.components.axi5.axi5_randomization_config import (
    AXI5RandomizationConfig,
)

# ---------------------------------------------------------------------------
# AXI4RandomizationConfig.randomize_fields (FIX: supported-field resolution)
# ---------------------------------------------------------------------------

class TestAXI4RandomizeFields:
    def test_supported_fields_are_signal_names(self):
        config = AXI4RandomizationConfig()
        supported = config._get_supported_fields()
        for name in ('awaddr', 'awlen', 'awsize', 'awburst', 'awid',
                     'wdata', 'wstrb', 'bresp', 'araddr', 'arlen',
                     'rdata', 'rresp'):
            assert name in supported, f"{name} missing from supported fields"
        # Channel names must no longer be the supported-field vocabulary
        assert 'AW' not in supported

    def test_randomize_fields_returns_values_for_all_requested_fields(self):
        config = AXI4RandomizationConfig(data_width=64, id_width=4)
        requests = {
            'awaddr': None, 'awlen': None, 'awsize': None,
            'awburst': None, 'awid': None, 'wdata': None,
            'bresp': None, 'arlen': None,
        }
        values = config.randomize_fields(requests)
        assert set(values.keys()) == set(requests.keys())

    def test_randomize_fields_respects_constraints(self):
        config = AXI4RandomizationConfig()
        for _ in range(20):
            values = config.randomize_fields({
                'awaddr': {'min': 0x1000, 'max': 0x8000, 'align': 64},
                'awlen': {'min': 4, 'max': 8},
                'awburst': {'types': [1]},
                'awid': {'min': 0, 'max': 3},
            })
            assert 0x1000 <= values['awaddr'] <= 0x8000
            assert values['awaddr'] % 64 == 0
            # AXI encodes burst length as len-1
            assert 3 <= values['awlen'] <= 7
            assert values['awburst'] == 1
            assert 0 <= values['awid'] <= 3

    def test_field_types_dispatch_correctly(self):
        """arlen/awsize must hit length/size randomizers, not address."""
        config = AXI4RandomizationConfig()
        for _ in range(20):
            values = config.randomize_fields({
                'arlen': None, 'arsize': None, 'arburst': None, 'rresp': None,
            })
            assert 0 <= values['arlen'] <= 255
            assert 0 <= values['arsize'] <= 3
            assert values['arburst'] in (0, 1, 2)
            assert values['rresp'] in (0, 1, 2, 3)

    def test_generic_field_uses_field_width(self):
        config = AXI4RandomizationConfig()
        for _ in range(20):
            values = config.randomize_fields({'awlock': None, 'awqos': None})
            assert values['awlock'] in (0, 1)       # 1-bit field
            assert 0 <= values['awqos'] <= 0xF      # 4-bit field

    def test_unsupported_field_is_skipped(self):
        config = AXI4RandomizationConfig()
        values = config.randomize_fields({'bogus_field': None, 'awaddr': None})
        assert 'bogus_field' not in values
        assert 'awaddr' in values

    def test_wdata_respects_data_width(self):
        config = AXI4RandomizationConfig(data_width=32)
        for _ in range(20):
            values = config.randomize_fields({'wdata': None})
            assert 0 <= values['wdata'] < (1 << 32)

    def test_profile_constraints_apply(self):
        config = AXI4RandomizationConfig(profile=AXI4RandomizationProfile.COMPLIANCE)
        for _ in range(20):
            values = config.randomize_fields({'awburst': None, 'awlen': None})
            assert values['awburst'] == 1           # COMPLIANCE: INCR only
            assert values['awlen'] <= 15            # burst_len_max=16 -> len-1


# ---------------------------------------------------------------------------
# AXI5RandomizationConfig.randomize_fields (same supported-field fix)
# ---------------------------------------------------------------------------

class TestAXI5RandomizeFields:
    def test_supported_fields_are_signal_names(self):
        config = AXI5RandomizationConfig()
        supported = config._get_supported_fields()
        for name in ('awaddr', 'awlen', 'arlen', 'wdata', 'bresp', 'rdata'):
            assert name in supported, f"{name} missing from supported fields"
        assert 'AW' not in supported

    def test_randomize_fields_returns_values(self):
        config = AXI5RandomizationConfig(data_width=32)
        for _ in range(20):
            values = config.randomize_fields({
                'awaddr': None, 'arlen': None, 'rdata': None, 'bresp': None,
            })
            assert set(values.keys()) == {'awaddr', 'arlen', 'rdata', 'bresp'}
            assert 0 <= values['arlen'] <= 255
            assert 0 <= values['rdata'] < (1 << 32)
            assert values['bresp'] in (0, 1, 2, 3)

    def test_unsupported_field_is_skipped(self):
        config = AXI5RandomizationConfig()
        values = config.randomize_fields({'not_a_field': None, 'araddr': None})
        assert 'not_a_field' not in values
        assert 'araddr' in values


# ---------------------------------------------------------------------------
# AXI4TimingConfig wrapper (FIX: previously did not exist -> import error)
# ---------------------------------------------------------------------------

class TestAXI4TimingConfig:
    def test_factory_returns_timing_config(self):
        timing = create_axi4_timing_config(['AW', 'AR'], 'fast')
        assert isinstance(timing, AXI4TimingConfig)
        assert timing.channels == ['AW', 'AR']
        assert timing.performance_mode == 'fast'

    def test_channel_configs_have_randomizer(self):
        timing = create_axi4_timing_config()
        configs = timing.get_channel_configs()
        assert set(configs.keys()) == {'AW', 'W', 'B', 'AR', 'R'}
        for cfg in configs.values():
            assert 'randomizer' in cfg
            assert 'profile_name' in cfg

    @pytest.mark.parametrize("mode,profile", [
        ('fast', 'axi4_fast'),
        ('normal', 'axi4_normal'),
        ('bursty', 'axi4_backtoback'),
        ('throttled', 'axi4_slow'),
        ('stress', 'axi4_stress'),
        ('unknown_mode', 'axi4_normal'),
    ])
    def test_performance_mode_profile_mapping(self, mode, profile):
        timing = AXI4TimingConfig(performance_mode=mode)
        assert timing.get_master_profile()['profile_name'] == profile

    def test_mode_switches_and_statistics(self):
        timing = AXI4TimingConfig()
        timing.set_performance_mode('stress')
        assert timing.get_slave_profile()['profile_name'] == 'axi4_stress'
        timing.enable_strict_handshakes()
        timing.enable_burst_mode()
        assert timing.get_monitor_profile()['profile_name'] == 'axi4_backtoback'
        timing.enable_variable_delays()
        stats = timing.get_statistics()
        assert stats['strict_handshakes'] is True
        assert stats['burst_mode'] is True
        assert stats['variable_delays'] is True


# ---------------------------------------------------------------------------
# AXI4RandomizationManager (FIX: module previously failed to import)
# ---------------------------------------------------------------------------

class TestAXI4RandomizationManager:
    def test_construct_with_defaults(self):
        manager = AXI4RandomizationManager()
        assert manager.channels == ['AW', 'W', 'B', 'AR', 'R']
        assert isinstance(manager.timing, AXI4TimingConfig)

    def test_master_config_generation(self):
        manager = create_unified_randomization(data_width=64)
        cfg = manager.create_master_config()
        assert set(cfg.keys()) >= {'protocol_randomizer', 'timing_randomizer', 'timing_config'}
        assert manager.protocol.master_mode is True
        assert manager.protocol.constraints.error_injection_rate == 0.0

    def test_slave_config_generation(self):
        manager = create_unified_randomization()
        cfg = manager.create_slave_config()
        assert 'timing_config' in cfg
        assert manager.protocol.master_mode is False
        assert manager.protocol.constraints.error_injection_rate == pytest.approx(0.01)

    def test_monitor_config_generation(self):
        manager = create_unified_randomization()
        cfg = manager.create_monitor_config(extra_key='x')
        assert 'timing_config' in cfg
        assert cfg['extra_key'] == 'x'

    def test_protocol_values_through_manager(self):
        manager = create_unified_randomization(data_width=32)
        values = manager.get_protocol_values({'awaddr': None, 'awlen': None, 'arid': None})
        assert set(values.keys()) == {'awaddr', 'awlen', 'arid'}
        assert manager.stats['protocol_calls'] == 1

    def test_timing_delays_through_manager(self):
        manager = create_unified_randomization()
        delays = manager.get_timing_delays(['AW', 'R'])
        assert set(delays.keys()) == {'AW', 'R'}
        assert manager.stats['timing_calls'] == 1

    def test_configuration_presets(self):
        manager = create_unified_randomization()
        manager.configure_for_compliance_testing()
        assert manager.protocol.constraints.error_injection_rate == 0.0
        manager.configure_for_performance_testing()
        assert manager.timing.get_master_profile()['profile_name'] == 'axi4_backtoback'
        manager.configure_for_error_injection(0.1)
        assert manager.protocol.constraints.error_injection_rate == pytest.approx(0.1)

    def test_statistics_roundtrip(self):
        manager = create_unified_randomization()
        manager.get_protocol_values({'awaddr': None})
        stats = manager.get_statistics()
        assert stats['protocol_calls'] == 1
        assert 'protocol_stats' in stats
        assert 'timing_stats' in stats
        manager.reset_statistics()
        assert manager.get_statistics()['protocol_calls'] == 0

    @pytest.mark.parametrize("factory", [
        create_compliance_randomization,
        create_performance_randomization,
        create_error_injection_randomization,
    ])
    def test_factory_functions(self, factory):
        manager = factory()
        assert isinstance(manager, AXI4RandomizationManager)
        # Every factory result must be able to generate real field values
        values = manager.get_protocol_values({'awaddr': None, 'awlen': None})
        assert set(values.keys()) == {'awaddr', 'awlen'}

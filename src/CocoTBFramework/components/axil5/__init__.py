# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""AXI5-Lite (AXIL5) components.

AXI4-Lite plus AXI5's optional signal groups (USER, TRACE, LOOP, MPAM, MECID,
NSAID, POISON, exclusive access). The interfaces subclass the AXIL4 ones and
swap in an AXI5-Lite field-config helper -- the channel logic is shared, not
copied, because the two protocols differ only in which optional fields exist.

With no feature switches an AXIL5 component is field-for-field an AXI4-Lite
component; see ``tests/unit/test_axil5_extends_axil4.py``.
"""

from .axil5_factories import (
    create_axil5_master,
    create_axil5_master_interface,
    create_axil5_master_rd,
    create_axil5_master_wr,
    create_axil5_slave,
    create_axil5_slave_interface,
    create_axil5_slave_rd,
    create_axil5_slave_wr,
    create_axil5_system,
    create_simple_axil5_master,
    create_simple_axil5_slave,
    get_unified_compliance_reports,
    is_unified_compliance_checking_enabled,
    print_all_compliance_reports_from_system,
    print_compliance_to_log,
    print_unified_compliance_reports,
)
from .axil5_field_configs import (
    AXIL5_FEATURE_KWARGS,
    AXIL5FieldConfigHelper,
    get_axil5_field_configs,
)
from .axil5_interfaces import (
    AXIL5MasterRead,
    AXIL5MasterWrite,
    AXIL5SlaveRead,
    AXIL5SlaveWrite,
)

from .axil5_timing_config import (
    create_axil5_randomizer_configs,
    create_axil5_timing_from_profile,
    get_axil5_timing_profiles,
    get_timing_for_axil5_feature,
)

from .axil5_transaction import (
    AXIL5Transaction,
    AXIL5TransactionTracker,
)
from .axil5_randomization_config import (
    AXIL5ConstraintSet,
    AXIL5ProtocolMode,
    AXIL5RandomizationConfig,
    AXIL5RandomizationProfile,
)
from .axil5_randomization_manager import (
    AXIL5RandomizationManager,
)
from .axil5_packet import (
    AXIL5Packet,
)
from .axil5_compliance_checker import (
    AXIL5ComplianceChecker,
    AXIL5Violation,
    AXIL5ViolationType,
)

__all__ = [
    "AXIL5ComplianceChecker",
    "AXIL5ConstraintSet",
    "AXIL5FieldConfigHelper",
    "AXIL5MasterRead",
    "AXIL5MasterWrite",
    "AXIL5Packet",
    "AXIL5ProtocolMode",
    "AXIL5RandomizationConfig",
    "AXIL5RandomizationManager",
    "AXIL5RandomizationProfile",
    "AXIL5SlaveRead",
    "AXIL5SlaveWrite",
    "AXIL5Transaction",
    "AXIL5TransactionTracker",
    "AXIL5Violation",
    "AXIL5ViolationType",
    "AXIL5_FEATURE_KWARGS",
    "create_axil5_master",
    "create_axil5_master_interface",
    "create_axil5_master_rd",
    "create_axil5_master_wr",
    "create_axil5_randomizer_configs",
    "create_axil5_slave",
    "create_axil5_slave_interface",
    "create_axil5_slave_rd",
    "create_axil5_slave_wr",
    "create_axil5_system",
    "create_axil5_timing_from_profile",
    "create_simple_axil5_master",
    "create_simple_axil5_slave",
    "get_axil5_field_configs",
    "get_axil5_timing_profiles",
    "get_timing_for_axil5_feature",
    "get_unified_compliance_reports",
    "is_unified_compliance_checking_enabled",
    "print_all_compliance_reports_from_system",
    "print_compliance_to_log",
    "print_unified_compliance_reports",
]

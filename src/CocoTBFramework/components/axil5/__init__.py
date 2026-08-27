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

__all__ = [
    "AXIL5_FEATURE_KWARGS",
    "AXIL5FieldConfigHelper",
    "AXIL5MasterRead",
    "AXIL5MasterWrite",
    "AXIL5SlaveRead",
    "AXIL5SlaveWrite",
    "create_axil5_master",
    "create_axil5_master_interface",
    "create_axil5_master_rd",
    "create_axil5_master_wr",
    "create_axil5_slave",
    "create_axil5_slave_interface",
    "create_axil5_slave_rd",
    "create_axil5_slave_wr",
    "create_axil5_system",
    "create_simple_axil5_master",
    "create_simple_axil5_slave",
    "get_axil5_field_configs",
    "get_unified_compliance_reports",
    "is_unified_compliance_checking_enabled",
    "print_all_compliance_reports_from_system",
    "print_compliance_to_log",
    "print_unified_compliance_reports",
]

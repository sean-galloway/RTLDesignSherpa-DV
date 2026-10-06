# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI4ACEFieldConfigHelper
# Purpose: ACE (AXI Coherency Extensions) field configuration helpers.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-05

"""ACE field configuration helpers.

This module extends the AXI4 field configurations with the ACE-specific
signals:

- ARSNOOP[3:0] on the AR channel
- AWSNOOP[2:0] on the AW channel
- ACADDR, ACSNOOP[3:0], ACPROT[2:0] on the snoop address channel
- CRRESP[4:0] on the snoop response channel
- CDDATA, CDLAST on the snoop data channel

The snoop fields are appended after the AXI4 user field so that the packed
payload order matches the RTL in ``rtl/amba/ace`` (snoop is packed last).
"""

from typing import Dict, List

from ..axi4.axi4_field_configs import AXI4FieldConfigHelper
from ..shared.field_config import FieldConfig, FieldDefinition


class AXI4ACEFieldConfigHelper:
    """Helper class for creating ACE field configurations."""

    @staticmethod
    def create_ar_field_config(
        id_width: int = 8,
        addr_width: int = 32,
        user_width: int = 1,
    ) -> FieldConfig:
        """
        Create field configuration for ACE Read Address (AR) channel.

        Extends the AXI4 AR config with ARSNOOP[3:0] appended after the
        user field to match the RTL payload order.

        Args:
            id_width: Width of ARID field
            addr_width: Width of ARADDR field
            user_width: Width of ARUSER field

        Returns:
            FieldConfig object for ACE AR channel
        """
        config = AXI4FieldConfigHelper.create_ar_field_config(
            id_width, addr_width, user_width
        )
        config.add_field(FieldDefinition(
            name="snoop",
            bits=4,
            default=0,
            format="hex",
            description="ACE Read Snoop Type (ARSNOOP)"
        ))
        return config

    @staticmethod
    def create_aw_field_config(
        id_width: int = 8,
        addr_width: int = 32,
        user_width: int = 1,
    ) -> FieldConfig:
        """
        Create field configuration for ACE Write Address (AW) channel.

        Extends the AXI4 AW config with AWSNOOP[2:0] appended after the
        user field to match the RTL payload order.

        Args:
            id_width: Width of AWID field
            addr_width: Width of AWADDR field
            user_width: Width of AWUSER field

        Returns:
            FieldConfig object for ACE AW channel
        """
        config = AXI4FieldConfigHelper.create_aw_field_config(
            id_width, addr_width, user_width
        )
        config.add_field(FieldDefinition(
            name="snoop",
            bits=3,
            default=0,
            format="hex",
            description="ACE Write Snoop Type (AWSNOOP)"
        ))
        return config

    @staticmethod
    def create_ac_field_config(
        addr_width: int = 32,
    ) -> FieldConfig:
        """
        Create field configuration for the snoop address (AC) channel.

        Args:
            addr_width: Width of ACADDR field

        Returns:
            FieldConfig object for AC channel
        """
        config = FieldConfig()
        config.add_field(FieldDefinition(
            name="addr",
            bits=addr_width,
            default=0,
            format="hex",
            description="Snoop Address (ACADDR)"
        ))
        config.add_field(FieldDefinition(
            name="snoop",
            bits=4,
            default=0,
            format="hex",
            description="Snoop Type (ACSNOOP)"
        ))
        config.add_field(FieldDefinition(
            name="prot",
            bits=3,
            default=0,
            format="bin",
            description="Snoop Protection (ACPROT)"
        ))
        return config

    @staticmethod
    def create_cr_field_config() -> FieldConfig:
        """
        Create field configuration for the snoop response (CR) channel.

        Returns:
            FieldConfig object for CR channel
        """
        config = FieldConfig()
        config.add_field(FieldDefinition(
            name="resp",
            bits=5,
            default=0,
            format="bin",
            description="Snoop Response (CRRESP)"
        ))
        return config

    @staticmethod
    def create_cd_field_config(
        data_width: int = 32,
    ) -> FieldConfig:
        """
        Create field configuration for the snoop data (CD) channel.

        Args:
            data_width: Width of CDDATA field

        Returns:
            FieldConfig object for CD channel
        """
        config = FieldConfig()
        config.add_field(FieldDefinition(
            name="data",
            bits=data_width,
            default=0,
            format="hex",
            description="Snoop Data (CDDATA)"
        ))
        config.add_field(FieldDefinition(
            name="last",
            bits=1,
            default=1,
            format="bin",
            description="Snoop Data Last (CDLAST)",
            encoding={0: "Not Last", 1: "Last"}
        ))
        return config

    @staticmethod
    def create_w_field_config(
        data_width: int = 32,
        user_width: int = 1,
    ) -> FieldConfig:
        """
        Create field configuration for the write data (W) channel.

        ACE does not change the W channel — this delegates to the AXI4
        config so callers can use one helper for the whole family.

        Args:
            data_width: Width of WDATA field
            user_width: Width of WUSER field

        Returns:
            FieldConfig object for W channel
        """
        return AXI4FieldConfigHelper.create_w_field_config(data_width, user_width)

    @staticmethod
    def create_b_field_config(
        id_width: int = 8,
        user_width: int = 1,
    ) -> FieldConfig:
        """
        Create field configuration for the write response (B) channel.

        ACE does not change the B channel — this delegates to the AXI4
        config so callers can use one helper for the whole family.

        Args:
            id_width: Width of BID field
            user_width: Width of BUSER field

        Returns:
            FieldConfig object for B channel
        """
        return AXI4FieldConfigHelper.create_b_field_config(id_width, user_width)

    @staticmethod
    def create_r_field_config(
        id_width: int = 8,
        data_width: int = 32,
        user_width: int = 1,
    ) -> FieldConfig:
        """
        Create field configuration for the read data (R) channel.

        ACE does not change the R channel — this delegates to the AXI4
        config so callers can use one helper for the whole family.

        Args:
            id_width: Width of RID field
            data_width: Width of RDATA field
            user_width: Width of RUSER field

        Returns:
            FieldConfig object for R channel
        """
        return AXI4FieldConfigHelper.create_r_field_config(id_width, data_width, user_width)

    @staticmethod
    def create_all_field_configs(
        id_width: int = 8,
        addr_width: int = 32,
        data_width: int = 32,
        user_width: int = 1,
        channels: List[str] = None,
    ) -> Dict[str, FieldConfig]:
        """
        Create field configurations for all specified ACE channels.

        Args:
            id_width: Width of ID fields
            addr_width: Width of address fields
            data_width: Width of data fields
            user_width: Width of user fields
            channels: List of channels to create configs for

        Returns:
            Dictionary mapping channel names to FieldConfig objects
        """
        if channels is None:
            channels = ['AW', 'W', 'B', 'AR', 'R', 'AC', 'CR', 'CD']

        creators = {
            'AW': lambda: AXI4ACEFieldConfigHelper.create_aw_field_config(
                id_width, addr_width, user_width
            ),
            'AR': lambda: AXI4ACEFieldConfigHelper.create_ar_field_config(
                id_width, addr_width, user_width
            ),
            'AC': lambda: AXI4ACEFieldConfigHelper.create_ac_field_config(addr_width),
            'CR': lambda: AXI4ACEFieldConfigHelper.create_cr_field_config(),
            'CD': lambda: AXI4ACEFieldConfigHelper.create_cd_field_config(data_width),
        }

        # AXI4 channels that are unchanged by ACE except for the protocol binding
        creators['W'] = lambda: AXI4FieldConfigHelper.create_w_field_config(
            data_width, user_width
        )
        creators['B'] = lambda: AXI4FieldConfigHelper.create_b_field_config(
            id_width, user_width
        )
        creators['R'] = lambda: AXI4FieldConfigHelper.create_r_field_config(
            id_width, data_width, user_width
        )

        configs = {}
        for channel in channels:
            if channel in creators:
                configs[channel] = creators[channel]()
            else:
                raise ValueError(f"Unknown ACE channel: {channel}")

        return configs


# Convenience functions for common use cases
def create_channel_field_config(
    channel: str,
    id_width: int = 8,
    addr_width: int = 32,
    data_width: int = 32,
    user_width: int = 1,
) -> FieldConfig:
    """Convenience function to create field config for a single ACE channel."""
    return AXI4ACEFieldConfigHelper.create_all_field_configs(
        id_width, addr_width, data_width, user_width, [channel]
    )[channel]


def get_axi4ace_field_configs(
    id_width: int = 8,
    addr_width: int = 32,
    data_width: int = 32,
    user_width: int = 1,
    channels: List[str] = None,
) -> Dict[str, FieldConfig]:
    """
    Get ACE field configurations for all specified channels.

    Args:
        id_width: Width of ID fields
        addr_width: Width of address fields
        data_width: Width of data fields
        user_width: Width of user fields
        channels: List of channels to create configs for

    Returns:
        Dictionary mapping channel names to FieldConfig objects
    """
    if channels is None:
        channels = ['AW', 'W', 'B', 'AR', 'R', 'AC', 'CR', 'CD']

    return AXI4ACEFieldConfigHelper.create_all_field_configs(
        id_width=id_width,
        addr_width=addr_width,
        data_width=data_width,
        user_width=user_width,
        channels=channels,
    )


if __name__ == "__main__":
    print("ACE Field Configuration Helpers - Testing")
    print("=" * 60)

    ar_cfg = AXI4ACEFieldConfigHelper.create_ar_field_config()
    print(f"AR config: {len(ar_cfg)} fields, {ar_cfg.get_total_bits()} total bits")
    print(f"AR fields: {list(ar_cfg.field_names())}")

    aw_cfg = AXI4ACEFieldConfigHelper.create_aw_field_config()
    print(f"AW config: {len(aw_cfg)} fields, {aw_cfg.get_total_bits()} total bits")
    print(f"AW fields: {list(aw_cfg.field_names())}")

    ac_cfg = AXI4ACEFieldConfigHelper.create_ac_field_config()
    print(f"AC config: {len(ac_cfg)} fields, {ac_cfg.get_total_bits()} total bits")
    print(f"AC fields: {list(ac_cfg.field_names())}")

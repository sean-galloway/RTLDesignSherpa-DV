# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI3FieldConfigHelper
# Purpose: AXI3 field configuration helpers reflecting the AXI3 protocol deltas.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""
AXI3 Field Configuration Helpers.

AXI3 differs from AXI4 in three ways that show up here:

* AWLEN/ARLEN are 4 bits (max 16 beats per burst).
* AWLOCK/ARLOCK are 2 bits (normal / exclusive / locked).
* There is no QoS and no REGION signalling.
* The W channel carries WID, so write-data interleaving by ID is legal.

This helper is a standalone copy of the AXI4 helper with those deltas applied;
AXI3 is its own protocol family, not a subclass of AXI4.  See issue #87.
"""

from typing import Dict, List, Tuple

from ..shared.field_config import FieldConfig, FieldDefinition


class AXI3FieldConfigHelper:
    """Helper class for creating AXI3 field configurations."""

    @staticmethod
    def create_aw_field_config(id_width: int = 8, addr_width: int = 32, user_width: int = 1) -> FieldConfig:
        """Create field configuration for AXI3 Write Address (AW) channel."""
        config = FieldConfig()

        config.add_field(FieldDefinition(
            name="id",
            bits=id_width,
            default=0,
            format="hex",
            description="Write Address ID"
        ))

        config.add_field(FieldDefinition(
            name="addr",
            bits=addr_width,
            default=0,
            format="hex",
            description="Write Address"
        ))

        config.add_field(FieldDefinition(
            name="len",
            bits=4,
            default=0,
            format="dec",
            description="Burst Length (0-15, meaning 1-16 beats)"
        ))

        config.add_field(FieldDefinition(
            name="size",
            bits=3,
            default=2,
            format="dec",
            description="Burst Size (bytes = 2^awsize)"
        ))

        config.add_field(FieldDefinition(
            name="burst",
            bits=2,
            default=1,
            format="dec",
            description="Burst Type (0=FIXED, 1=INCR, 2=WRAP)",
            encoding={0: "FIXED", 1: "INCR", 2: "WRAP"}
        ))

        config.add_field(FieldDefinition(
            name="lock",
            bits=2,
            default=0,
            format="bin",
            description="Lock Type (0=Normal, 1=Exclusive, 2=Locked)",
            encoding={0: "Normal", 1: "Exclusive", 2: "Locked"}
        ))

        config.add_field(FieldDefinition(
            name="cache",
            bits=4,
            default=0,
            format="bin",
            description="Cache Type"
        ))

        config.add_field(FieldDefinition(
            name="prot",
            bits=3,
            default=0,
            format="bin",
            description="Protection Type"
        ))

        if user_width > 0:
            config.add_field(FieldDefinition(
                name="user",
                bits=user_width,
                default=0,
                format="bin",
                description="User Signal"
            ))

        return config

    @staticmethod
    def create_w_field_config(id_width: int = 8, data_width: int = 32, user_width: int = 1) -> FieldConfig:
        """Create field configuration for AXI3 Write Data (W) channel.

        AXI3 W carries WID, which is what makes write-data interleaving legal.
        """
        strb_width = data_width // 8
        config = FieldConfig()

        config.add_field(FieldDefinition(
            name="id",
            bits=id_width,
            default=0,
            format="hex",
            description="Write Data ID (WID)"
        ))

        config.add_field(FieldDefinition(
            name="data",
            bits=data_width,
            default=0,
            format="hex",
            description="Write Data"
        ))

        config.add_field(FieldDefinition(
            name="strb",
            bits=strb_width,
            default=(1 << strb_width) - 1,
            format="bin",
            description="Write Strobe (byte enables)"
        ))

        config.add_field(FieldDefinition(
            name="last",
            bits=1,
            default=1,
            format="bin",
            description="Write Last (end of burst)",
            encoding={0: "Not Last", 1: "Last"}
        ))

        if user_width > 0:
            config.add_field(FieldDefinition(
                name="user",
                bits=user_width,
                default=0,
                format="bin",
                description="User Signal"
            ))

        return config

    @staticmethod
    def create_b_field_config(id_width: int = 8, user_width: int = 1) -> FieldConfig:
        """Create field configuration for AXI3 Write Response (B) channel."""
        config = FieldConfig()

        config.add_field(FieldDefinition(
            name="id",
            bits=id_width,
            default=0,
            format="hex",
            description="Response ID"
        ))

        config.add_field(FieldDefinition(
            name="resp",
            bits=2,
            default=0,
            format="dec",
            description="Write Response",
            encoding={0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
        ))

        if user_width > 0:
            config.add_field(FieldDefinition(
                name="user",
                bits=user_width,
                default=0,
                format="bin",
                description="User Signal"
            ))

        return config

    @staticmethod
    def create_ar_field_config(id_width: int = 8, addr_width: int = 32, user_width: int = 1) -> FieldConfig:
        """Create field configuration for AXI3 Read Address (AR) channel."""
        config = FieldConfig()

        config.add_field(FieldDefinition(
            name="id",
            bits=id_width,
            default=0,
            format="hex",
            description="Read Address ID"
        ))

        config.add_field(FieldDefinition(
            name="addr",
            bits=addr_width,
            default=0,
            format="hex",
            description="Read Address"
        ))

        config.add_field(FieldDefinition(
            name="len",
            bits=4,
            default=0,
            format="dec",
            description="Burst Length (0-15, meaning 1-16 beats)"
        ))

        config.add_field(FieldDefinition(
            name="size",
            bits=3,
            default=2,
            format="dec",
            description="Burst Size (bytes = 2^arsize)"
        ))

        config.add_field(FieldDefinition(
            name="burst",
            bits=2,
            default=1,
            format="dec",
            description="Burst Type (0=FIXED, 1=INCR, 2=WRAP)",
            encoding={0: "FIXED", 1: "INCR", 2: "WRAP"}
        ))

        config.add_field(FieldDefinition(
            name="lock",
            bits=2,
            default=0,
            format="bin",
            description="Lock Type (0=Normal, 1=Exclusive, 2=Locked)",
            encoding={0: "Normal", 1: "Exclusive", 2: "Locked"}
        ))

        config.add_field(FieldDefinition(
            name="cache",
            bits=4,
            default=0,
            format="bin",
            description="Cache Type"
        ))

        config.add_field(FieldDefinition(
            name="prot",
            bits=3,
            default=0,
            format="bin",
            description="Protection Type"
        ))

        if user_width > 0:
            config.add_field(FieldDefinition(
                name="user",
                bits=user_width,
                default=0,
                format="bin",
                description="User Signal"
            ))

        return config

    @staticmethod
    def create_r_field_config(id_width: int = 8, data_width: int = 32, user_width: int = 1) -> FieldConfig:
        """Create field configuration for AXI3 Read Data (R) channel."""
        config = FieldConfig()

        config.add_field(FieldDefinition(
            name="id",
            bits=id_width,
            default=0,
            format="hex",
            description="Read Data ID"
        ))

        config.add_field(FieldDefinition(
            name="data",
            bits=data_width,
            default=0,
            format="hex",
            description="Read Data"
        ))

        config.add_field(FieldDefinition(
            name="resp",
            bits=2,
            default=0,
            format="dec",
            description="Read Response",
            encoding={0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
        ))

        config.add_field(FieldDefinition(
            name="last",
            bits=1,
            default=1,
            format="bin",
            description="Read Last (end of burst)",
            encoding={0: "Not Last", 1: "Last"}
        ))

        if user_width > 0:
            config.add_field(FieldDefinition(
                name="user",
                bits=user_width,
                default=0,
                format="bin",
                description="User Signal"
            ))

        return config

    @staticmethod
    def create_all_field_configs(id_width: int = 8, addr_width: int = 32,
                                data_width: int = 32, user_width: int = 1,
                                channels: List[str] = ['AW', 'W', 'B', 'AR', 'R']) -> Dict[str, FieldConfig]:
        """Create field configurations for all specified AXI3 channels."""
        creators = {
            'AW': lambda: AXI3FieldConfigHelper.create_aw_field_config(id_width, addr_width, user_width),
            'W':  lambda: AXI3FieldConfigHelper.create_w_field_config(id_width, data_width, user_width),
            'B':  lambda: AXI3FieldConfigHelper.create_b_field_config(id_width, user_width),
            'AR': lambda: AXI3FieldConfigHelper.create_ar_field_config(id_width, addr_width, user_width),
            'R':  lambda: AXI3FieldConfigHelper.create_r_field_config(id_width, data_width, user_width),
        }

        configs = {}
        for channel in channels:
            if channel in creators:
                configs[channel] = creators[channel]()
            else:
                raise ValueError(f"Unknown AXI3 channel: {channel}")

        return configs

    @staticmethod
    def validate_axi3_widths(id_width: int, addr_width: int, data_width: int, user_width: int) -> Tuple[bool, List[str]]:
        """Validate AXI3 field width parameters."""
        errors = []

        if not (1 <= id_width <= 16):
            errors.append(f"id_width must be 1-16 bits, got {id_width}")

        if not (1 <= addr_width <= 64):
            errors.append(f"addr_width must be 1-64 bits, got {addr_width}")

        valid_data_widths = [8, 16, 32, 64, 128, 256, 512, 1024]
        if data_width not in valid_data_widths:
            errors.append(f"data_width must be one of {valid_data_widths}, got {data_width}")

        if not (0 <= user_width <= 32):
            errors.append(f"user_width must be 0-32 bits, got {user_width}")

        return len(errors) == 0, errors

    @staticmethod
    def preview_field_configs(id_width: int = 8, addr_width: int = 32,
                            data_width: int = 32, user_width: int = 1,
                            channels: List[str] = ['AW', 'W', 'B', 'AR', 'R']) -> None:
        """Preview field configurations for debugging."""
        print("\nAXI3 Field Configuration Preview")
        print(f"ID Width: {id_width}, Addr Width: {addr_width}, Data Width: {data_width}, User Width: {user_width}")
        print("-" * 70)

        is_valid, errors = AXI3FieldConfigHelper.validate_axi3_widths(id_width, addr_width, data_width, user_width)
        if not is_valid:
            print("Invalid Parameters:")
            for error in errors:
                print(f"   {error}")
            return

        try:
            configs = AXI3FieldConfigHelper.create_all_field_configs(id_width, addr_width, data_width, user_width, channels)

            for channel, config in configs.items():
                print(f"\n{channel} Channel ({len(config)} fields, {config.get_total_bits()} total bits):")
                for field_name, field_def in config.items():
                    encoding_str = f" ({', '.join(f'{k}={v}' for k, v in field_def.encoding.items())})" if field_def.encoding else ""
                    print(f"   {field_name:10} [{field_def.bits:2d}] = {field_def.default:4d} ({field_def.format}){encoding_str}")

        except Exception as e:
            print(f"Error creating configs: {e}")


def create_channel_field_config(channel: str, id_width: int = 8, addr_width: int = 32,
                            data_width: int = 32, user_width: int = 1) -> FieldConfig:
    """Convenience function to create field config for a single channel."""
    return AXI3FieldConfigHelper.create_all_field_configs(
        id_width, addr_width, data_width, user_width, [channel]
    )[channel]


def get_axi3_field_configs(id_width: int = 8, addr_width: int = 32,
                        data_width: int = 32, user_width: int = 1,
                        channels: List[str] = ['AW', 'W', 'B', 'AR', 'R']) -> Dict[str, FieldConfig]:
    """Get AXI3 field configurations for all specified channels."""
    return AXI3FieldConfigHelper.create_all_field_configs(
        id_width=id_width,
        addr_width=addr_width,
        data_width=data_width,
        user_width=user_width,
        channels=channels
    )


if __name__ == "__main__":
    print("AXI3 Field Configuration Helpers - Testing")
    print("=" * 50)

    aw_config = AXI3FieldConfigHelper.create_aw_field_config(id_width=4, addr_width=32)
    print(f"AW config: {len(aw_config)} fields, {aw_config.get_total_bits()} total bits")

    is_valid, errors = AXI3FieldConfigHelper.validate_axi3_widths(4, 32, 32, 1)
    print(f"Validation: {is_valid}, errors: {errors}")

    AXI3FieldConfigHelper.preview_field_configs(id_width=4, data_width=64, channels=['AW', 'W'])

    print("\nTesting get_axi3_field_configs function:")
    field_configs = get_axi3_field_configs(id_width=4, data_width=64, channels=['AW', 'AR'])
    print(f"Got {len(field_configs)} configurations: {list(field_configs.keys())}")

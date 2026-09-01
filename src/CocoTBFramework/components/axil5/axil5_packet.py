# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5Packet
# Purpose: AXI5-Lite packet -- AXIL4Packet on the AXI5-Lite field configs
#
# Subsystem: framework

"""AXI5-Lite packet.

``AXIL4Packet`` with the AXI5-Lite field-config helper swapped in, exactly as
``AXIL5MasterRead`` is ``AXIL4MasterRead`` with the helper swapped. The packing,
field access and formatting all come from the shared ``Packet`` base and are not
restated here.

The constructors take the optional-group widths as keyword arguments and pass
them to the helper, which adds a field only when its group is enabled. So a
packet built with no groups has exactly the AXI4-Lite field set -- the same
property the interfaces rely on, at the packet layer.
"""
from CocoTBFramework.components.axil4.axil4_packet import AXIL4Packet
from CocoTBFramework.components.axil5.axil5_field_configs import AXIL5FieldConfigHelper


class AXIL5Packet(AXIL4Packet):
    """An AXI4-Lite packet whose field config may carry the AXI5-Lite groups."""

    #: Swapped by AXIL5 so the inherited constructors build AXI5-Lite configs.
    FIELD_CONFIG_HELPER = AXIL5FieldConfigHelper

    @classmethod
    def create_aw_packet(cls, addr_width: int = 32, **field_values):
        """Write Address packet. Optional-group kwargs (``user_width``,
        ``trace``, ``loop_width``, ``mpam_width``, ``mecid_width``,
        ``nsaid_width``, ``exclusive``) are forwarded to the helper; omit them
        all and the field set is AXI4-Lite's."""
        opts, values = cls._split_options(field_values)
        return cls(cls.FIELD_CONFIG_HELPER.create_aw_field_config(addr_width, **opts),
                   **values)

    @classmethod
    def create_ar_packet(cls, addr_width: int = 32, **field_values):
        """Read Address packet. Same optional groups as AW -- AXI5-Lite's two
        address channels are symmetric, unlike AXI5's."""
        opts, values = cls._split_options(field_values)
        return cls(cls.FIELD_CONFIG_HELPER.create_ar_field_config(addr_width, **opts),
                   **values)

    @classmethod
    def create_w_packet(cls, data_width: int = 32, **field_values):
        """Write Data packet. Carries USER and POISON only: TRACE, LOOP and
        MPAM ride the address channel, not the data."""
        opts, values = cls._split_options(field_values)
        return cls(cls.FIELD_CONFIG_HELPER.create_w_field_config(data_width, **opts),
                   **values)

    @classmethod
    def create_b_packet(cls, **field_values):
        """Write Response packet: RESP plus USER, TRACE and LOOP."""
        opts, values = cls._split_options(field_values)
        return cls(cls.FIELD_CONFIG_HELPER.create_b_field_config(**opts), **values)

    @classmethod
    def create_r_packet(cls, data_width: int = 32, **field_values):
        """Read Data packet: DATA/RESP plus USER, TRACE, LOOP and POISON."""
        opts, values = cls._split_options(field_values)
        return cls(cls.FIELD_CONFIG_HELPER.create_r_field_config(data_width, **opts),
                   **values)

    #: Keyword arguments that configure the FIELD SET rather than set a value.
    _OPTION_KEYS = frozenset({
        'user_width', 'trace', 'loop_width', 'mpam_width', 'mecid_width',
        'nsaid_width', 'poison', 'exclusive',
    })

    @classmethod
    def _split_options(cls, kwargs):
        """Separate group-enable kwargs from actual field values.

        Without this a caller writing ``create_aw_packet(addr=0x10, mpam_width=11)``
        would have ``mpam_width`` treated as a field to set, and the packet
        would have no MPAM field at all -- the option silently doing nothing.
        """
        opts = {k: v for k, v in kwargs.items() if k in cls._OPTION_KEYS}
        values = {k: v for k, v in kwargs.items() if k not in cls._OPTION_KEYS}
        return opts, values

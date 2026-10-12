# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5FieldConfigHelper
# Purpose: AXI5-Lite field configurations -- AXI4-Lite plus optional groups
#
# Subsystem: framework

"""AXI5-Lite (AXIL5) field configurations.

AXI5-Lite is AXI4-Lite plus the transaction ID and a set of OPTIONAL signal
groups (IHI 0022 Issue L, section B2.1.5 and Table B2.2). The channel
structure is unchanged -- five channels, single beat, same required fields
(``addr``/``prot``, ``data``/``strb``, ``resp``) -- so this helper extends
:class:`AXIL4FieldConfigHelper` rather than restating it. With no ID and every
group disabled the configs are field-for-field identical to AXI4-Lite, which is
asserted in ``tests/unit/test_axil5_extends_axil4.py``; that equality is what
keeps the two from drifting into separate protocols.

Every group is off by default. A DUT gets exactly the fields it implements,
which matters more here than elsewhere: a field declared but not present on
the DUT is a fatal bind error (see the strict rule in
``shared/signal_mapping_helper.py``), and a field present but not declared is
never driven or checked at all.

Signals modelled here, with their Table B2.2 AXI5-Lite presence code:

``id_width``
    AWID / BID (ID_W_WIDTH) and ARID / RID (ID_R_WIDTH), code YS: optional on
    a Manager, mandatory on a Subordinate. A Subordinate reflects AxID on the
    matching response (Issue L A5.1.1). One width serves both directions here,
    as it does in the RTL.
``user_width``
    AWUSER / WUSER / BUSER / ARUSER / RUSER, code O.
``trace``
    AWTRACE / ARTRACE / BTRACE / RTRACE, 1 bit, code O.
``poison``
    WPOISON / RPOISON, code O. One bit per 64 data bits, minimum one, so the
    width is derived from the data width rather than passed in.

NOT modelled, because Table B2.2 marks them "N" (not present) on AXI5-Lite:
AxLOCK (exclusive accesses are not supported, B2.1.5), AxMPAM, AxMECID,
AxNSAID, AxLOOP/xLOOP, bursts (``len``/``size``/``burst``), cache, QoS,
REGION, atomics, memory tagging and read-data chunking. A BFM that offered
them would let a testbench drive signals no AXI5-Lite interface can carry.
(AxSIZE, AxSUBSYSID, xIDUNQ and WTRACE are "O" and simply not implemented.)

Every field added here defaults to 0 meaning "not in use" (an ID of all
zeros is the spec default), which is what makes them all legal entries in the
``optional_fields`` sets -- see the zero-default rule in
``shared/signal_mapping_helper.py``.
"""

from typing import Dict, List

from ..axil4.axil4_field_configs import AXIL4FieldConfigHelper
from ..shared.field_config import FieldConfig, FieldDefinition

# Widths the AXI5-Lite spec fixes. Everything else is implementation-defined
# and therefore a caller argument.
TRACE_BITS = 1
ID_MAX_BITS = 32              # Table A5.2: ID_W_WIDTH / ID_R_WIDTH are 0..32
POISON_BITS_PER = 64          # one poison bit per 64 data bits


def _add_id(config: FieldConfig, id_width: int, description: str) -> None:
    """Append the ``id`` field when the caller gave the interface an ID."""
    if id_width > ID_MAX_BITS:
        raise ValueError(f"id_width={id_width} exceeds the AXI5 maximum of "
                         f"{ID_MAX_BITS} (IHI 0022L Table A5.2)")
    _add_optional(config, "id", id_width, "hex", description)


def _add_optional(config: FieldConfig, name: str, bits: int, fmt: str,
                  description: str) -> None:
    """Append an optional-group field when the caller enabled it (bits > 0)."""
    if bits <= 0:
        return
    config.add_field(FieldDefinition(
        name=name, bits=bits, default=0, format=fmt, description=description,
    ))


class AXIL5FieldConfigHelper(AXIL4FieldConfigHelper):
    """AXI5-Lite field configurations: AXI4-Lite plus enabled optional groups.

    Each method takes the AXI4-Lite config from the base class and appends only
    the groups the caller turned on, so the AXI4-Lite fields keep one
    definition and cannot drift between the two protocols.
    """

    # ---- address channels (AW / AR) -------------------------------------
    @staticmethod
    def _add_addr_options(config: FieldConfig, direction: str, *,
                          id_width: int = 0, user_width: int = 0,
                          trace: bool = False, **_ignored) -> FieldConfig:
        """Append the AW/AR ID and optional groups. ``direction`` is
        'Write'/'Read'.

        Switches belonging to other channels (``poison``) are accepted and
        ignored, because ``create_all_field_configs`` hands the full option set
        to every channel so one call configures a whole interface.
        """
        _add_id(config, id_width, f"{direction} Transaction ID")
        _add_optional(config, "user", user_width, "hex",
                      f"{direction} Address User")
        _add_optional(config, "trace", TRACE_BITS if trace else 0, "bin",
                      f"{direction} Trace")
        return config

    @staticmethod
    def create_aw_field_config(addr_width: int = 32, **options) -> FieldConfig:
        """AXI5-Lite AW: AWADDR/AWPROT plus any enabled optional groups."""
        config = AXIL4FieldConfigHelper.create_aw_field_config(addr_width)
        return AXIL5FieldConfigHelper._add_addr_options(
            config, "Write", **options)

    @staticmethod
    def create_ar_field_config(addr_width: int = 32, **options) -> FieldConfig:
        """AXI5-Lite AR: ARADDR/ARPROT plus any enabled optional groups."""
        config = AXIL4FieldConfigHelper.create_ar_field_config(addr_width)
        return AXIL5FieldConfigHelper._add_addr_options(
            config, "Read", **options)

    # ---- data / response channels ---------------------------------------
    @staticmethod
    def create_w_field_config(data_width: int = 32, *, user_width: int = 0,
                              poison: bool = False, **_ignored) -> FieldConfig:
        """AXI5-Lite W: WDATA/WSTRB plus WUSER and WPOISON when enabled.

        The W channel carries no ID (AXI5 has no WID) and no trace here: those
        ride the address channel and are already associated with the
        transaction by the time data flows.
        """
        config = AXIL4FieldConfigHelper.create_w_field_config(data_width)
        _add_optional(config, "user", user_width, "hex", "Write Data User")
        # One poison bit per 64 data bits, minimum one -- a 32-bit bus still
        # has a single poison bit covering its one (partial) 64-bit chunk.
        poison_bits = max(1, data_width // POISON_BITS_PER) if poison else 0
        _add_optional(config, "poison", poison_bits, "bin", "Write Data Poison")
        return config

    @staticmethod
    def create_r_field_config(data_width: int = 32, *, id_width: int = 0,
                              user_width: int = 0, trace: bool = False,
                              poison: bool = False, **_ignored) -> FieldConfig:
        """AXI5-Lite R: RDATA/RRESP plus RID, RUSER, RTRACE, RPOISON."""
        config = AXIL4FieldConfigHelper.create_r_field_config(data_width)
        _add_id(config, id_width, "Read Data ID")
        _add_optional(config, "user", user_width, "hex", "Read Data User")
        _add_optional(config, "trace", TRACE_BITS if trace else 0, "bin",
                      "Read Trace")
        poison_bits = max(1, data_width // POISON_BITS_PER) if poison else 0
        _add_optional(config, "poison", poison_bits, "bin", "Read Data Poison")
        return config

    @staticmethod
    def create_b_field_config(*, id_width: int = 0, user_width: int = 0,
                              trace: bool = False, **_ignored) -> FieldConfig:
        """AXI5-Lite B: BRESP plus BID, BUSER, BTRACE when enabled."""
        config = AXIL4FieldConfigHelper.create_b_field_config()
        _add_id(config, id_width, "Write Response ID")
        _add_optional(config, "user", user_width, "hex", "Write Response User")
        _add_optional(config, "trace", TRACE_BITS if trace else 0, "bin",
                      "Write Response Trace")
        return config

    @staticmethod
    def create_all_field_configs(addr_width: int = 32, data_width: int = 32,
                                 channels: List[str] = None,
                                 **options) -> Dict[str, FieldConfig]:
        """Field configs for every requested AXI5-Lite channel.

        ``options`` are the optional-group switches; each channel takes the
        subset that applies to it and ignores the rest, so one call configures
        a whole interface consistently.
        """
        if channels is None:
            channels = ['AW', 'W', 'B', 'AR', 'R']
        H = AXIL5FieldConfigHelper
        configs = {}
        if 'AW' in channels:
            configs['AW'] = H.create_aw_field_config(addr_width, **options)
        if 'W' in channels:
            configs['W'] = H.create_w_field_config(data_width, **options)
        if 'B' in channels:
            configs['B'] = H.create_b_field_config(**options)
        if 'AR' in channels:
            configs['AR'] = H.create_ar_field_config(addr_width, **options)
        if 'R' in channels:
            configs['R'] = H.create_r_field_config(data_width, **options)
        return configs


#: Optional-group switches accepted by the helper and by the AXIL5 interfaces.
#: Interfaces pull exactly these keys out of ``**kwargs``; anything else is a
#: normal interface argument. Keeping the list here means a new group is added
#: in one place rather than in four constructors.
AXIL5_FEATURE_KWARGS = (
    'id_width', 'user_width', 'trace', 'poison',
)


def get_axil5_field_configs(addr_width: int = 32, data_width: int = 32,
                            **options) -> Dict[str, FieldConfig]:
    """Standard AXI5-Lite field configurations for all five channels."""
    return AXIL5FieldConfigHelper.create_all_field_configs(
        addr_width, data_width, **options)

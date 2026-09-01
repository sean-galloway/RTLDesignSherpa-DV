# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5 interfaces
# Purpose: AXI5-Lite master/slave BFMs -- AXIL4 interfaces + optional groups
#
# Subsystem: framework

"""AXI5-Lite (AXIL5) master and slave interfaces.

These are the AXI4-Lite interfaces with an AXI5-Lite field-config helper
swapped in. That is the whole difference, and it is deliberate: AXI5-Lite adds
optional signal groups to AXI4-Lite without changing a single channel's
handshake, ordering or response semantics, so the transaction logic is not
merely similar, it is the same logic. Copying it would produce two
implementations of one protocol with nothing comparing them -- the failure
mode this framework has already paid for more than once.

So every transaction method (``read_transaction``, ``write_transaction``,
``single_read``, ``read_register``, the compliance hooks) is inherited
unchanged and is not restated here. What each class below contributes is two
lines: which field-config helper to use, and how to turn the caller's
optional-group kwargs into arguments for it.

Usage mirrors AXIL4 exactly, plus the feature switches::

    from CocoTBFramework.components.axil5 import AXIL5MasterWrite

    master = AXIL5MasterWrite(
        dut, clock, prefix="s_axil_",
        data_width=64, addr_width=32,
        multi_sig=True,
        user_width=4,        # AWUSER/WUSER/BUSER present, 4 bits
        trace=True,          # AWTRACE/BTRACE present
        mpam_width=11,       # AWMPAM present
    )

With no feature switches an AXIL5 component drives and checks exactly the
AXI4-Lite signal set, so pointing one at an AXI4-Lite DUT is valid and is what
``tests/unit/test_axil5_extends_axil4.py`` pins.

Signal naming: AXIL5 has no entry of its own in ``PROTOCOL_SIGNAL_CONFIGS`` --
like AXI4-Lite its channels resolve through the generic ``gaxi_*`` patterns
from ``prefix`` + ``pkt_prefix``, so ``prefix="s_axil_"`` finds
``s_axil_awaddr``, ``s_axil_awuser``, ``s_axil_awtrace`` and so on with no
per-protocol table to maintain.
"""

from ..axil4.axil4_interfaces import (
    AXIL4MasterRead,
    AXIL4MasterWrite,
    AXIL4SlaveRead,
    AXIL4SlaveWrite,
)
from .axil5_field_configs import AXIL5_FEATURE_KWARGS, AXIL5FieldConfigHelper


class _AXIL5FeatureMixin:
    """Routes the AXI5-Lite optional-group kwargs into the field-config helper.

    ``_build_field_config_options`` is the hook the AXIL4 interfaces call while
    building each channel. Pulling the switches out of ``**kwargs`` here means
    the four classes below share one definition of what an AXI5-Lite feature
    is, so adding a group touches ``AXIL5_FEATURE_KWARGS`` alone.

    Only keys the caller actually passed are forwarded. An absent switch must
    stay absent rather than become an explicit zero, so that the helper's own
    defaults remain the single statement of what "feature off" means.
    """

    FIELD_CONFIG_HELPER = AXIL5FieldConfigHelper

    # Resolve through the axil5_* protocol entries, whose optional_fields sets
    # allow the AXI5-Lite groups to be absent from a DUT that was built without
    # them. Under axil4_* they were not optional and a mismatch died at signal
    # resolution instead of reading the spec default of 0.
    PROTOCOL_FAMILY = 'axil5'

    @staticmethod
    def _build_field_config_options(kwargs):
        return {k: kwargs[k] for k in AXIL5_FEATURE_KWARGS if k in kwargs}


class AXIL5MasterRead(_AXIL5FeatureMixin, AXIL4MasterRead):
    """AXI5-Lite master read (drives AR, receives R)."""


class AXIL5MasterWrite(_AXIL5FeatureMixin, AXIL4MasterWrite):
    """AXI5-Lite master write (drives AW and W, receives B)."""


class AXIL5SlaveRead(_AXIL5FeatureMixin, AXIL4SlaveRead):
    """AXI5-Lite slave read (receives AR, drives R)."""


class AXIL5SlaveWrite(_AXIL5FeatureMixin, AXIL4SlaveWrite):
    """AXI5-Lite slave write (receives AW and W, drives B)."""

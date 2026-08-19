"""Constructing the DFI slave path for a device we ship no timings for.

Every other DFI unit test builds its objects with `object.__new__` to
skip the constructor, because a live cocotb entity is not available. That
is fine for testing decode logic, and it is also why nobody noticed that
`DFIBase` takes `timings` as a mandatory argument with no profile
available for HBM4, DDR5, LPDDR5 or LPDDR6 — the CA maps decoded
perfectly in tests while a consumer could not get far enough to use
them.

These go through the real `DFIBase.__init__` for an unshipped device, so
the construction path stays exercised rather than assumed.
"""

import pytest

from CocoTBFramework.components.dfi import (
    AddressMapping,
    DFIBase,
    timings_from_params,
)
from CocoTBFramework.components.dfi.dfi_signals import DFIVersion, MemoryType

# Stand-in for numbers a consumer reads off a vendor datasheet. They are
# not claimed to describe any real part -- the point is the plumbing.
_VENDOR_TIMINGS = dict(
    tCK_ns=0.5, tRCD_ns=14.0, tRP_ns=14.0, tRAS_min_ns=29.0, tRC_ns=43.0,
    tWR_ns=15.0, tWTR_ns=7.5, tRTP_ns=7.5, tRRD_ns=4.0, tFAW_ns=16.0,
    tREFI_ns=3900.0, tRFC_ns=260.0, CL=32, CWL=30, BL=8,
)


def _mapping():
    return AddressMapping(num_ranks=1, num_banks=32,
                          num_rows=1 << 15, num_cols=1 << 6)


def test_hbm4_base_constructs_with_supplied_timings():
    """The case that motivated this: JESD270-4A leaves HBM4 AC timings
    vendor-defined, so no profile can ever ship, and the device was
    therefore unusable end to end."""
    base = DFIBase(
        dfi_version=DFIVersion.V6_0,
        memory_type=MemoryType.HBM4,
        timings=timings_from_params(**_VENDOR_TIMINGS),
        mapping=_mapping(),
    )
    assert base.memory_type is MemoryType.HBM4
    assert base.timings.tRCD_cycles == 28          # ceil(14.0 / 0.5)


@pytest.mark.parametrize("mem_type,version", [
    (MemoryType.DDR5, DFIVersion.V5_2),
    (MemoryType.LPDDR5, DFIVersion.V5_2),
])
def test_other_unshipped_devices_construct_too(mem_type, version):
    base = DFIBase(
        dfi_version=version,
        memory_type=mem_type,
        timings=timings_from_params(**_VENDOR_TIMINGS),
        mapping=_mapping(),
    )
    assert base.memory_type is mem_type


def test_supplied_timings_are_carried_through_unaltered():
    """Whatever the consumer supplies is what the checker enforces; a
    silent substitution of defaults would be worse than a hard failure."""
    timings = timings_from_params(**_VENDOR_TIMINGS)
    base = DFIBase(
        dfi_version=DFIVersion.V6_0,
        memory_type=MemoryType.HBM4,
        timings=timings,
        mapping=_mapping(),
    )
    assert base.timings == timings

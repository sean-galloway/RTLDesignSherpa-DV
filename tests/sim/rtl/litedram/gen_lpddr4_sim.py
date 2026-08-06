# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Generate a standalone LiteDRAM LPDDR4 core for DFI co-sim.

``litedram_gen --sim`` has no LPDDR4 path: litex_sim's
``get_sdram_phy_settings`` raises on the memtype and gen.py's sim CRG
rate dict has no LPDDR4 key. Both gaps are worked around here rather
than by forking litedram:

  1. The YAML declares ``memtype: DDR3`` — that key is only consumed
     by gen.py's rate/CRG dicts (→ 1:4, a spec-legal DFI ratio for
     LPDDR4) and cosmetic constants. Everything real (controller
     timings, init sequence, PHY settings) derives from the
     ``sdram_module`` — MT53E256M16D1, whose ``memtype`` is LPDDR4.
  2. ``get_sdram_phy_settings`` is wrapped to handle LPDDR4 with the
     DDR4-branch math at nphases=4 and JEDEC LPDDR4 latencies
     (RL=14 / WL=8, JESD209-4 Table 28), before delegating everything
     else to the original.

Run (after ``source env_python``):
    python tests/sim/rtl/litedram/gen_lpddr4_sim.py

Output: tests/sim/rtl/litedram/lpddr4/gateware/litedram_core.v
"""

from __future__ import annotations

import os
import shutil
import sys

import litex.tools.litex_sim as litex_sim
from litedram.common import PhySettings, get_sys_latency, get_sys_phase

_original_get_settings = litex_sim.get_sdram_phy_settings

# JEDEC LPDDR4 latencies (JESD209-4 Table 28, DBI off, WL set A,
# 533-800 MHz range): RL=14 pairs with WL=8 — litedram's init-sequence
# generator validates the pair against that table.
LPDDR4_CL = 14
LPDDR4_CWL = 8
LPDDR4_NPHASES = 4


def _lpddr4_aware_settings(memtype, data_width, clk_freq):
    if memtype != "LPDDR4":
        return _original_get_settings(memtype, data_width, clk_freq)

    nphases = LPDDR4_NPHASES
    cl, cwl = LPDDR4_CL, LPDDR4_CWL
    cl_sys_latency = get_sys_latency(nphases, cl)
    cwl_sys_latency = get_sys_latency(nphases, cwl)
    rdphase = get_sys_phase(nphases, cl_sys_latency, cl)
    wrphase = get_sys_phase(nphases, cwl_sys_latency, cwl)

    return PhySettings(
        phytype       = "SDRAMPHYModel",
        memtype       = memtype,
        databits      = data_width,
        dfi_databits  = 2 * data_width,
        nphases       = nphases,
        rdphase       = rdphase,
        wrphase       = wrphase,
        cl            = cl,
        cwl           = cwl,
        read_latency  = cl_sys_latency + 6,
        write_latency = cwl_sys_latency,
    )


def _patch_phy_model() -> None:
    """SDRAMPHYModel.__init__ keys an internal burst-length dict on
    settings.memtype and has no LPDDR4 entry. Present the memtype as
    DDR4 (same burst granularity per DFI phase) for the duration of
    the constructor, then restore it so the controller and the init-
    sequence generator still see LPDDR4."""
    from litedram.phy.model import SDRAMPHYModel

    orig_init = SDRAMPHYModel.__init__

    def patched_init(self, module, settings=None, **kwargs):
        if settings is not None and settings.memtype == "LPDDR4":
            settings.memtype = "DDR4"
            try:
                orig_init(self, module, settings=settings, **kwargs)
            finally:
                settings.memtype = "LPDDR4"
        else:
            orig_init(self, module, settings=settings, **kwargs)

    SDRAMPHYModel.__init__ = patched_init


def main() -> None:
    litex_sim.get_sdram_phy_settings = _lpddr4_aware_settings
    _patch_phy_model()

    here = os.path.dirname(os.path.abspath(__file__))
    yaml = os.path.join(here, "arty_lpddr4_nocpu.yml")
    out_dir = os.path.join(here, "lpddr4")
    shutil.rmtree(out_dir, ignore_errors=True)

    from litedram.gen import main as gen_main
    sys.argv = [
        "litedram_gen", "--sim", "--no-compile",
        "--output-dir", out_dir, yaml,
    ]
    gen_main()

    core_v = os.path.join(out_dir, "gateware", "litedram_core.v")
    assert os.path.exists(core_v), f"generation produced no {core_v}"
    with open(core_v) as f:
        lines = sum(1 for _ in f)
    print(f"\nGenerated: {core_v} ({lines} lines)")


if __name__ == "__main__":
    main()

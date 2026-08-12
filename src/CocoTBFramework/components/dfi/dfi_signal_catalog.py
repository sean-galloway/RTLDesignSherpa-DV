# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Spec-verified DFI signal catalog, v2.1 through v6.0.

Every entry below was transcribed from the signal tables of the actual
specification PDFs (chapter 3 "Interface Signal Groups" of each):

  - DFI v2.1.1  (Denali, 17 Jun 2010)  — Tables 2-14
  - DFI v3.1    (Cadence, ~2014)       — chapter 3, Tables per interface
  - DFI v4.0    (Cadence, 27 Apr 2018) — chapter 3, sections 3.1-3.13
  - DFI v5.2    (Cadence, 15 Oct 2024) — chapter 3, Tables 13-44
  - DFI v6.0    (Cadence, 8 May 2026)  — chapter 3, Tables 23-53

Version lifecycle is encoded per signal via ``min_version`` /
``max_version``. Renames are two entries: the old name ends at its
``max_version``, the new name starts at its ``min_version``. The
notable rename sweeps:

  v3.0:  dfi_parity_error → dfi_alert_n; training interface redesigned
         (mode/load/delay/edge signals dropped, en/req/resp handshakes kept)
  v3.1:  dfi_lp_req → dfi_lp_ctrl_req (+ new dfi_lp_data_req)
  v4.0:  every ``*_cs_n`` → ``*_cs`` (dfi_cs_n → dfi_cs, dfi_rddata_cs_n →
         dfi_rddata_cs, …); dfi_rddata_dbi_n → dfi_rddata_dbi
  v5.x:  ENTIRE training + DB-training interfaces removed (training is
         PHY-internal via PHY Managed / PHY Independent Mode);
         dfi_phymstr_* → dfi_phymngd_* (5.2); dfi_freq_ratio →
         dfi_cmd_freq_ratio + dfi_data_freq_ratio (5.2); low-power ack/
         wakeup split into ctrl/data pairs (5.1)
  v6.0:  dfi_address → dfi_cmdaddr; dfi_alert_n → dfi_alert (polarity
         follows memory); dfi_reset_n → dfi_reset; dfi_parity_in →
         dfi_caparity; dfi_error/_info → dfi_phy_error/_info;
         dfi_wrdata_mask → dfi_wrdata_dbi_mask; unpacked command signals
         (bank/ras_n/cas_n/we_n/cke/odt/act_n/bg/cid) and the disconnect
         protocol removed

Sub-interface assignment follows the latest spec that carries the
signal (e.g. dfi_parity_in sits in Status in v2.1-v4.0 but Command in
v5.2 — we file it under COMMAND and note the move in the description).
"""

from __future__ import annotations

from typing import FrozenSet, Optional, Tuple

from .dfi_signal_types import (
    WIDTH_ADDR,
    WIDTH_ALERT,
    WIDTH_BANK,
    WIDTH_BANK_GROUP,
    WIDTH_CHIP_ID,
    WIDTH_CS,
    WIDTH_CS_X_DATA_EN,
    WIDTH_CTRL,
    WIDTH_DATA,
    WIDTH_DATA_DIV8,
    WIDTH_DATA_EN,
    WIDTH_EIGHT_BITS,
    WIDTH_FIVE_BITS,
    WIDTH_ONE_BIT,
    WIDTH_PER_SLICE,
    WIDTH_RANK,
    WIDTH_RD_VALID,
    WIDTH_SIXTEEN_BITS,
    WIDTH_THREE_BITS,
    WIDTH_TWO_BITS,
    WIDTH_WCK,
    DFIVersion,
    MemoryType,
    SignalDirection,
    SignalSpec,
    SubInterface,
)

_MC = SignalDirection.MC_TO_PHY
_PHY = SignalDirection.PHY_TO_MC

V2_1 = DFIVersion.V2_1
V3_1 = DFIVersion.V3_1
V4_0 = DFIVersion.V4_0
V5_2 = DFIVersion.V5_2
V6_0 = DFIVersion.V6_0

_ALL: FrozenSet[MemoryType] = frozenset()  # empty = applies to all types

_DDR_CMD = frozenset({
    # bank/ras_n/cas_n/we_n users; LPDDR2/3/4 hold these idle per spec
    MemoryType.DDR1, MemoryType.LPDDR1, MemoryType.DDR2,
    MemoryType.DDR3, MemoryType.DDR4,
})
_ODT = frozenset({
    MemoryType.DDR2, MemoryType.DDR3, MemoryType.DDR4, MemoryType.LPDDR3,
})
_RESET = frozenset({
    # v2.1: DDR3 only; v4.0 adds DDR4/LPDDR4; v5.2 adds DDR5/LPDDR5
    MemoryType.DDR3, MemoryType.DDR4, MemoryType.DDR5,
    MemoryType.LPDDR4, MemoryType.LPDDR5,
})
_DDR4 = frozenset({MemoryType.DDR4})
_DDR4_5 = frozenset({MemoryType.DDR4, MemoryType.DDR5})
_DDR5 = frozenset({MemoryType.DDR5})
_3DS = frozenset({MemoryType.DDR3, MemoryType.DDR4})
_PARITY = frozenset({MemoryType.DDR3, MemoryType.DDR4, MemoryType.DDR5})
_LPDDR2 = frozenset({MemoryType.LPDDR2})
_DBI = frozenset({MemoryType.DDR4, MemoryType.LPDDR4, MemoryType.LPDDR5})
_CALVL = frozenset({
    MemoryType.LPDDR2, MemoryType.LPDDR3, MemoryType.LPDDR4,
})
_RDLVL = frozenset({
    MemoryType.DDR3, MemoryType.DDR4, MemoryType.LPDDR2,
    MemoryType.LPDDR3, MemoryType.LPDDR4,
})
_WRLVL = frozenset({MemoryType.DDR3, MemoryType.DDR4})
# WCK memberships (v6.0 Table 13): wck_en / wck_toggle are required for
# LPDDR5, LPDDR6, AND HBM4; wck_cs only for LPDDR5/LPDDR6 (multi-CS).
# Named _WCK_MEM* because plain _WCK gets rebound to
# SubInterface.WCK_CONTROL further down — that shadowing silently
# replaced these frozensets with an enum and made every WCK signal
# unresolvable for every memory type (fixed alongside HBM4 support).
_WCK_MEM = frozenset({MemoryType.LPDDR5, MemoryType.LPDDR6})
_WCK_MEM_ALL = frozenset({MemoryType.LPDDR5, MemoryType.LPDDR6,
                          MemoryType.HBM4})
_LPDDR5 = frozenset({MemoryType.LPDDR5})
_HBM4 = frozenset({MemoryType.HBM4})


def _s(
    name: str,
    direction: SignalDirection,
    width_key: str,
    sub_interface: SubInterface,
    min_version: DFIVersion,
    description: str,
    memory_types: FrozenSet[MemoryType] = _ALL,
    max_version: Optional[DFIVersion] = None,
) -> SignalSpec:
    """Compact SignalSpec constructor for the tables below."""
    return SignalSpec(
        name=name,
        direction=direction,
        width_key=width_key,
        sub_interface=sub_interface,
        min_version=min_version,
        memory_types=memory_types,
        description=description,
        max_version=max_version,
    )


_CI = SubInterface.COMMAND

# --------------------------------------------------------------------
# Command interface ("Control Interface" pre-v5.x)
# --------------------------------------------------------------------
COMMAND_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("address", _MC, WIDTH_ADDR, _CI, V2_1,
       "Command/address bus; per-memory CA mapping (LPDDR2: 20-bit CA). "
       "Renamed dfi_cmdaddr in v6.0.", max_version=V5_2),
    _s("cmdaddr", _MC, WIDTH_ADDR, _CI, V6_0,
       "Encoded CA bus (v6.0 rename of dfi_address); per-protocol bit "
       "mappings (LPDDR5 14b, LPDDR6 8/11b, DDR5 14b, HBM4 R/C)"),
    _s("bank", _MC, WIDTH_BANK, _CI, V2_1,
       "Bank address; LPDDR2/3/4 hold idle. Removed in v6.0.",
       memory_types=_DDR_CMD, max_version=V5_2),
    _s("ras_n", _MC, WIDTH_CTRL, _CI, V2_1,
       "Row address strobe; DDR4 dual-purpose (A16 when act_n asserted). "
       "Removed in v6.0.", memory_types=_DDR_CMD, max_version=V5_2),
    _s("cas_n", _MC, WIDTH_CTRL, _CI, V2_1,
       "Column address strobe; DDR4 dual-purpose (A15 when act_n "
       "asserted). Removed in v6.0.", memory_types=_DDR_CMD,
       max_version=V5_2),
    _s("we_n", _MC, WIDTH_CTRL, _CI, V2_1,
       "Write enable; DDR4 dual-purpose (A14 when act_n asserted). "
       "Removed in v6.0.", memory_types=_DDR_CMD, max_version=V5_2),
    _s("cke", _MC, WIDTH_CS, _CI, V2_1,
       "Clock enable (reset value memory-dependent per spec footnote). "
       "Removed in v6.0.", max_version=V5_2),
    _s("cs_n", _MC, WIDTH_CS, _CI, V2_1,
       "Chip select, active low. Renamed dfi_cs in v4.0.",
       max_version=V3_1),
    _s("cs", _MC, WIDTH_CS, _CI, V4_0,
       "Chip select (v4.0 rename of dfi_cs_n; default 0x1; polarity "
       "follows the memory signal from v6.0)"),
    _s("odt", _MC, WIDTH_CS, _CI, V2_1,
       "On-die termination control (DDR2/3/4 + LPDDR3). Removed in v6.0.",
       memory_types=_ODT, max_version=V5_2),
    _s("reset_n", _MC, WIDTH_CS, _CI, V2_1,
       "Memory reset (v2.1: DDR3; v4.0: +DDR4/LPDDR4; v5.x: +DDR5/"
       "LPDDR5). Renamed dfi_reset in v6.0.", memory_types=_RESET,
       max_version=V5_2),
    _s("reset", _MC, WIDTH_CS, _CI, V6_0,
       "Memory reset (v6.0 rename of dfi_reset_n; polarity follows the "
       "memory signal)"),
    _s("act_n", _MC, WIDTH_ONE_BIT, _CI, V3_1,
       "DDR4 ACT command encoding; other memories hold idle. Removed in "
       "v6.0.", memory_types=_DDR4, max_version=V5_2),
    _s("bg", _MC, WIDTH_BANK_GROUP, _CI, V3_1,
       "DDR4 bank group. Removed in v6.0.", memory_types=_DDR4,
       max_version=V5_2),
    _s("cid", _MC, WIDTH_CHIP_ID, _CI, V3_1,
       "Chip ID for 3DS stacked devices (DDR3/DDR4). Removed in v6.0.",
       memory_types=_3DS, max_version=V5_2),
    _s("parity_in", _MC, WIDTH_ONE_BIT, _CI, V2_1,
       "MC-computed command parity (v2.1: DDR3 registered DIMM; v3.0+: "
       "DDR4 CA parity; listed under Status pre-v5.x, Command in v5.2). "
       "Renamed dfi_caparity in v6.0.", memory_types=_PARITY,
       max_version=V5_2),
    _s("caparity", _MC, WIDTH_ONE_BIT, _CI, V6_0,
       "CA parity (v6.0 rename of dfi_parity_in); encoding defined by "
       "the memory protocol"),
    _s("alert_n", _PHY, WIDTH_ALERT, _CI, V3_1,
       "CRC / CA-parity error indicator, active low (v3.0 rename of "
       "v2.1's dfi_parity_error; reflects DDR4 ALERT_n; listed under "
       "Status pre-v5.x, Command in v5.2). Renamed dfi_alert in v6.0.",
       memory_types=_PARITY, max_version=V5_2),
    _s("alert", _PHY, WIDTH_ALERT, _CI, V6_0,
       "Common error signal (v6.0 rename of dfi_alert_n; polarity "
       "follows the memory signal, e.g. DDR5 ALERT_n)"),
    _s("2n_mode", _MC, WIDTH_ONE_BIT, _CI, V5_2,
       "2N command timing mode (introduced with the 5.1 proposals; "
       "optional DDR4, required DDR5)", memory_types=_DDR4_5),
    _s("cs_geardown", _MC, WIDTH_ONE_BIT, _CI, V5_2,
       "DDR5 CS geardown", memory_types=_DDR5),
    _s("geardown_en", _MC, WIDTH_ONE_BIT, _CI, V4_0,
       "DDR4 geardown mode (CA at 1/2 memory clock); v4.0 only — "
       "superseded by dfi_2n_mode/dfi_cs_geardown in v5.x",
       memory_types=_DDR4, max_version=V4_0),
    _s("cmd_en", _MC, WIDTH_ONE_BIT, _CI, V6_0,
       "Command bus enable (new in v6.0)"),
    _s("data_alert", _PHY, WIDTH_ALERT, _CI, V6_0,
       "Separate write-data error signal for protocols with distinct CA "
       "and write-data error paths (e.g. HBM4); new in v6.0"),
)

_WD = SubInterface.WRITE_DATA

# --------------------------------------------------------------------
# Write data interface
# --------------------------------------------------------------------
WRITE_DATA_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("wrdata", _MC, WIDTH_DATA, _WD, V2_1,
       "Write data; begins 1 cycle after wrdata_en assertion. Also "
       "carries the MC-generated CRC word for DDR4 when phycrc_mode=0 "
       "(v4.0+)."),
    _s("wrdata_en", _MC, WIDTH_DATA_EN, _WD, V2_1,
       "Write data enable; asserted tphy_wrlat cycles after write cmd"),
    _s("wrdata_mask", _MC, WIDTH_DATA_DIV8, _WD, V2_1,
       "Byte mask (1 bit per 8 wrdata bits); doubles as write DBI when "
       "DBI is enabled with phydbi_mode=0 (v3.0+). Renamed "
       "dfi_wrdata_dbi_mask in v6.0.", max_version=V5_2),
    _s("wrdata_dbi_mask", _MC, WIDTH_DATA_DIV8, _WD, V6_0,
       "Write DBI / data mask (v6.0 rename of dfi_wrdata_mask); function "
       "depends on system/DRAM settings"),
    _s("wrdata_cs_n", _MC, WIDTH_CS_X_DATA_EN, _WD, V3_1,
       "Write-data chip select, active low (v3.0; also the CS-under-"
       "training indicator during write leveling). Renamed "
       "dfi_wrdata_cs in v4.0.", max_version=V3_1),
    _s("wrdata_cs", _MC, WIDTH_RANK, _WD, V4_0,
       "Write-data chip select (v4.0 rename of dfi_wrdata_cs_n); lets "
       "the PHY compensate data-path timing per target rank"),
    _s("wrdata_crc", _MC, WIDTH_DATA_DIV8, _WD, V5_2,
       "Link DQ CRC for DDR5 MRDIMM Mux Mode (phylinkdqcrc_mode=1)",
       memory_types=_DDR5),
    _s("wrdata_ecc", _MC, WIDTH_DATA_DIV8, _WD, V5_2,
       "Write ECC (v5.x: LPDDR5 Link ECC when phylinkecc_mode=1; v6.0: "
       "protocols with ECC pins such as HBM4)",
       memory_types=frozenset({MemoryType.LPDDR5, MemoryType.HBM4})),
    _s("wrparity", _MC, WIDTH_DATA_DIV8, _WD, V6_0,
       "Write data parity bus (new in v6.0); encoding per memory "
       "protocol"),
)

_RD = SubInterface.READ_DATA

# --------------------------------------------------------------------
# Read data interface
# --------------------------------------------------------------------
READ_DATA_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("rddata", _PHY, WIDTH_DATA, _RD, V2_1,
       "Read data; valid when rddata_valid asserts"),
    _s("rddata_en", _MC, WIDTH_DATA_EN, _RD, V2_1,
       "Read data enable; asserted trddata_en after read cmd"),
    _s("rddata_valid", _PHY, WIDTH_RD_VALID, _RD, V2_1,
       "Read data valid; asserted with rddata, max tphy_rdlat after "
       "rddata_en; per-data-slice independent timing from v3.0"),
    _s("rddata_dnv", _PHY, WIDTH_DATA_DIV8, _RD, V2_1,
       "Data-not-valid, byte-granular (LPDDR2 NVM feature). Removed in "
       "v6.0.", memory_types=_LPDDR2, max_version=V5_2),
    _s("rddata_dbi_n", _PHY, WIDTH_DATA_DIV8, _RD, V3_1,
       "Read DBI, active low (v3.0, DDR4, phydbi_mode=0). Renamed "
       "dfi_rddata_dbi in v4.0.", memory_types=_DDR4, max_version=V3_1),
    _s("rddata_dbi", _PHY, WIDTH_DATA_DIV8, _RD, V4_0,
       "Read DBI (v4.0 rename of dfi_rddata_dbi_n; DDR4/LPDDR4/LPDDR5); "
       "in v6.0 doubles as Link ECC on shared-pin protocols (LPDDR5)",
       memory_types=_DBI),
    _s("rddata_cs_n", _MC, WIDTH_CS_X_DATA_EN, _RD, V3_1,
       "Read-data chip select, active low (v3.0; also CS-under-training "
       "indicator during read training). Renamed dfi_rddata_cs in "
       "v4.0.", max_version=V3_1),
    _s("rddata_cs", _MC, WIDTH_RANK, _RD, V4_0,
       "Read-data chip select (v4.0 rename of dfi_rddata_cs_n)"),
    _s("rddata_crc", _PHY, WIDTH_DATA_DIV8, _RD, V5_2,
       "Link DQ CRC for DDR5 MRDIMM Mux Mode (phylinkdqcrc_mode=1). "
       "Spec tables print From=MC — almost certainly a typo for PHY "
       "(read path); we encode PHY.", memory_types=_DDR5),
    _s("rddata_ecc", _PHY, WIDTH_DATA_DIV8, _RD, V6_0,
       "Read ECC for protocols with a dedicated ECC pin (e.g. HBM4)",
       memory_types=_HBM4),
    _s("rddata_sev", _PHY, WIDTH_TWO_BITS, _RD, V6_0,
       "Read data error severity (optional; some memory protocols only)"),
    _s("rdparity", _PHY, WIDTH_DATA_DIV8, _RD, V6_0,
       "Read data parity bus (new in v6.0)"),
    _s("rdparity_valid", _PHY, WIDTH_RD_VALID, _RD, V6_0,
       "Read parity valid (new in v6.0)"),
)

_UP = SubInterface.UPDATE

# --------------------------------------------------------------------
# Update interface — bidirectional since v2.1 (NOT a v3.0 addition)
# --------------------------------------------------------------------
UPDATE_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("ctrlupd_req", _MC, WIDTH_ONE_BIT, _UP, V2_1,
       "MC-initiated update request; assertion bounded by tctrlupd_min/"
       "max. v4.0+: handshake required immediately before self-refresh "
       "exit."),
    _s("ctrlupd_ack", _PHY, WIDTH_ONE_BIT, _UP, V2_1,
       "PHY acknowledge of MC-initiated update (PHY may ignore)"),
    _s("phyupd_req", _PHY, WIDTH_ONE_BIT, _UP, V2_1,
       "PHY-initiated update request; MC MUST acknowledge"),
    _s("phyupd_ack", _MC, WIDTH_ONE_BIT, _UP, V2_1,
       "MC acknowledge of PHY-initiated update; asserted within "
       "tphyupd_resp and held while phyupd_req is high"),
    _s("phyupd_type", _PHY, WIDTH_TWO_BITS, _UP, V2_1,
       "PHY update type (selects tphyupd_typeX duration; up to 4 modes)"),
)

_ST = SubInterface.STATUS

# --------------------------------------------------------------------
# Status interface — owns init / frequency change since v2.1
# --------------------------------------------------------------------
STATUS_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("dram_clk_disable", _MC, WIDTH_CS, _ST, V2_1,
       "DRAM clock disable. Filed under STATUS (its v2.1-v4.0 home) so "
       "the default command/write/read wiring profile stays lean; the "
       "v5.2+ books list it in the Command Interface chapter."),
    _s("init_start", _MC, WIDTH_ONE_BIT, _ST, V2_1,
       "At init: MC ready, freq_ratio/data_byte_disable valid. During "
       "operation: frequency-change request (PHY accepts by de-"
       "asserting init_complete within tinit_start; ignoring = request "
       "withdrawn)."),
    _s("init_complete", _PHY, WIDTH_ONE_BIT, _ST, V2_1,
       "PHY ready for DFI transactions; de-assertion acknowledges a "
       "frequency-change request"),
    _s("freq_ratio", _MC, WIDTH_TWO_BITS, _ST, V2_1,
       "MC:PHY frequency ratio (00=1:1, 01=1:2, 10=1:4). Split into "
       "dfi_cmd_freq_ratio + dfi_data_freq_ratio in v5.2.",
       max_version=V4_0),
    _s("cmd_freq_ratio", _MC, WIDTH_TWO_BITS, _ST, V5_2,
       "Command-interface frequency ratio (v5.2 split of "
       "dfi_freq_ratio; backward compat = 'b00); 3 bits with 1:3/1:6 "
       "ratios in v6.0"),
    _s("data_freq_ratio", _MC, WIDTH_TWO_BITS, _ST, V5_2,
       "Data-interface frequency ratio (v5.2 split of dfi_freq_ratio; "
       "adds 1:8='b11); 3 bits in v6.0"),
    _s("frequency", _MC, WIDTH_FIVE_BITS, _ST, V4_0,
       "Frequency indicator (v4.0: 5 bits/32 encodings; v5.x: up to 6 "
       "bits/64; encoding PHY/system-defined via phyfreq_range); must "
       "be valid and stable while init_start is asserted"),
    _s("freq_fsp", _MC, WIDTH_TWO_BITS, _ST, V5_2,
       "Frequency set point for the new target frequency (memories with "
       "multiple FSPs; timing follows dfi_frequency)"),
    _s("data_byte_disable", _MC, WIDTH_DATA_DIV8, _ST, V2_1,
       "Static per-byte disable defined at init. REMOVED in v4.0 "
       "(replaced by the dfidata_bit_enable programmable parameter).",
       max_version=V3_1),
    _s("parity_error", _PHY, WIDTH_ONE_BIT, _ST, V2_1,
       "Command parity error from DDR3 registered DIMMs (v2.1.1 parity "
       "interface). Renamed dfi_alert_n in v3.0.",
       memory_types=frozenset({MemoryType.DDR3}), max_version=V2_1),
    _s("sleep", _MC, WIDTH_ONE_BIT, _ST, V6_0,
       "Sleep protocol request (new in v6.0; tsleep_* timing family)"),
)

_TR = SubInterface.TRAINING

# --------------------------------------------------------------------
# Training interface — exists v2.1 through v4.0 ONLY. v3.0 redesigned
# the v2.1 delay-register protocol into en/req/resp handshakes; v5.x
# removed DFI training entirely (PHY-internal via PHY Managed).
# --------------------------------------------------------------------
TRAINING_SIGNALS: Tuple[SignalSpec, ...] = (
    # --- v2.1-only delay-register protocol ---
    _s("rdlvl_mode", _PHY, WIDTH_TWO_BITS, _TR, V2_1,
       "v2.1 read-leveling mode (00=disabled, MC/PHY evaluation modes). "
       "Dropped in the v3.0 training redesign.", memory_types=_RDLVL,
       max_version=V2_1),
    _s("rdlvl_gate_mode", _PHY, WIDTH_TWO_BITS, _TR, V2_1,
       "v2.1 gate-training mode. Dropped in v3.0.", memory_types=_RDLVL,
       max_version=V2_1),
    _s("rdlvl_edge", _MC, WIDTH_ONE_BIT, _TR, V2_1,
       "v2.1 read-leveling edge select. Dropped in v3.0.",
       memory_types=_RDLVL, max_version=V2_1),
    _s("rdlvl_delay", _MC, WIDTH_PER_SLICE, _TR, V2_1,
       "v2.1 per-slice read-leveling delay (dfi_rdlvl_delay_X fanout). "
       "Dropped in v3.0.", memory_types=_RDLVL, max_version=V2_1),
    _s("rdlvl_gate_delay", _MC, WIDTH_PER_SLICE, _TR, V2_1,
       "v2.1 per-slice gate delay (dfi_rdlvl_gate_delay_X fanout). "
       "Dropped in v3.0.", memory_types=_RDLVL, max_version=V2_1),
    _s("rdlvl_load", _MC, WIDTH_ONE_BIT, _TR, V2_1,
       "v2.1 read-leveling delay load strobe. Dropped in v3.0.",
       memory_types=_RDLVL, max_version=V2_1),
    _s("rdlvl_cs_n", _MC, WIDTH_CS, _TR, V2_1,
       "v2.1 read-leveling chip select. Dropped in v3.0 (per-CS "
       "signaling moved to dfi_rddata_cs_n).", memory_types=_RDLVL,
       max_version=V2_1),
    _s("wrlvl_mode", _PHY, WIDTH_TWO_BITS, _TR, V2_1,
       "v2.1 write-leveling mode. Dropped in v3.0.", memory_types=_WRLVL,
       max_version=V2_1),
    _s("wrlvl_delay", _MC, WIDTH_PER_SLICE, _TR, V2_1,
       "v2.1 per-slice write-leveling delay (dfi_wrlvl_delay_X fanout). "
       "Dropped in v3.0.", memory_types=_WRLVL, max_version=V2_1),
    _s("wrlvl_load", _MC, WIDTH_ONE_BIT, _TR, V2_1,
       "v2.1 write-leveling delay load strobe. Dropped in v3.0.",
       memory_types=_WRLVL, max_version=V2_1),
    _s("wrlvl_cs_n", _MC, WIDTH_CS, _TR, V2_1,
       "v2.1 write-leveling chip select. Dropped in v3.0.",
       memory_types=_WRLVL, max_version=V2_1),
    # --- handshake signals that span v2.1 through v4.0 ---
    _s("rdlvl_req", _PHY, WIDTH_PER_SLICE, _TR, V2_1,
       "PHY requests read leveling (per-slice from v4.0). Training "
       "interface removed in v5.x.", memory_types=_RDLVL,
       max_version=V4_0),
    _s("rdlvl_gate_req", _PHY, WIDTH_PER_SLICE, _TR, V2_1,
       "PHY requests gate training (per-slice from v4.0). Removed in "
       "v5.x.", memory_types=_RDLVL, max_version=V4_0),
    _s("rdlvl_en", _MC, WIDTH_PER_SLICE, _TR, V2_1,
       "MC enables read leveling (per-slice from v4.0). Removed in "
       "v5.x.", memory_types=_RDLVL, max_version=V4_0),
    _s("rdlvl_gate_en", _MC, WIDTH_PER_SLICE, _TR, V2_1,
       "MC enables gate training (per-slice from v4.0). Removed in "
       "v5.x.", memory_types=_RDLVL, max_version=V4_0),
    _s("rdlvl_resp", _PHY, WIDTH_PER_SLICE, _TR, V2_1,
       "Read-leveling response/status from PHY. Removed in v5.x.",
       memory_types=_RDLVL, max_version=V4_0),
    _s("rdlvl_done", _MC, WIDTH_PER_SLICE, _TR, V4_0,
       "MC signals read-leveling completion (v4.0). Removed in v5.x.",
       memory_types=_RDLVL, max_version=V4_0),
    _s("wrlvl_req", _PHY, WIDTH_PER_SLICE, _TR, V2_1,
       "PHY requests write leveling. Removed in v5.x.",
       memory_types=_WRLVL, max_version=V4_0),
    _s("wrlvl_en", _MC, WIDTH_PER_SLICE, _TR, V2_1,
       "MC enables write leveling. Removed in v5.x.",
       memory_types=_WRLVL, max_version=V4_0),
    _s("wrlvl_strobe", _MC, WIDTH_PER_SLICE, _TR, V2_1,
       "Write-leveling strobe pulse (per-slice with syswrlvl_strobe_num "
       "from v4.0). Removed in v5.x.", memory_types=_WRLVL,
       max_version=V4_0),
    _s("wrlvl_resp", _PHY, WIDTH_PER_SLICE, _TR, V2_1,
       "Write-leveling sample response from PHY. Removed in v5.x.",
       memory_types=_WRLVL, max_version=V4_0),
    # --- v3.x additions ---
    _s("lvl_pattern", _MC, WIDTH_TWO_BITS, _TR, V3_1,
       "Training pattern select (v3.0; becomes an index into programmed "
       "patterns for LPDDR4 in v4.0). Removed in v5.x.",
       max_version=V4_0),
    _s("lvl_periodic", _MC, WIDTH_ONE_BIT, _TR, V3_1,
       "Periodic-training indicator (v3.0). Removed in v5.x.",
       max_version=V4_0),
    _s("phy_rdlvl_cs_n", _PHY, WIDTH_CS, _TR, V3_1,
       "CS the PHY wants trained (read leveling), active low (v3.0). "
       "Renamed dfi_phy_rdlvl_cs in v4.0.", memory_types=_RDLVL,
       max_version=V3_1),
    _s("phy_rdlvl_gate_cs_n", _PHY, WIDTH_CS, _TR, V3_1,
       "CS the PHY wants trained (gate training), active low (v3.0). "
       "Renamed in v4.0.", memory_types=_RDLVL, max_version=V3_1),
    _s("phy_wrlvl_cs_n", _PHY, WIDTH_CS, _TR, V3_1,
       "CS the PHY wants trained (write leveling), active low (v3.0). "
       "Renamed in v4.0.", memory_types=_WRLVL, max_version=V3_1),
    _s("phy_rdlvl_cs", _PHY, WIDTH_RANK, _TR, V4_0,
       "CS under read-leveling training (v4.0 rename). Removed in v5.x.",
       memory_types=_RDLVL, max_version=V4_0),
    _s("phy_rdlvl_gate_cs", _PHY, WIDTH_RANK, _TR, V4_0,
       "CS under gate training (v4.0 rename). Removed in v5.x.",
       memory_types=_RDLVL, max_version=V4_0),
    _s("phy_wrlvl_cs", _PHY, WIDTH_RANK, _TR, V4_0,
       "CS under write-leveling training (v4.0 rename). Removed in "
       "v5.x.", memory_types=_WRLVL, max_version=V4_0),
    _s("phylvl_req_cs_n", _PHY, WIDTH_CS, _TR, V3_1,
       "PHY-requested training: per-CS request (v3.1, PHY-independent "
       "training in non-DFI training mode). Superseded by v4.0 PHY "
       "Independent Mode.", max_version=V3_1),
    _s("phylvl_ack_cs_n", _MC, WIDTH_CS, _TR, V3_1,
       "PHY-requested training: per-CS MC acknowledge (v3.1). "
       "Superseded by v4.0 PHY Independent Mode.", max_version=V3_1),
    # --- CA training (LPDDR3 v3.1; LPDDR4 VREF additions v4.0) ---
    _s("calvl_en", _MC, WIDTH_PER_SLICE, _TR, V3_1,
       "MC enables CA training (v3.1, LPDDR3; LPDDR4 from v4.0). "
       "Removed in v5.x.", memory_types=_CALVL, max_version=V4_0),
    _s("calvl_req", _PHY, WIDTH_PER_SLICE, _TR, V3_1,
       "PHY requests CA training (v3.1). Removed in v5.x.",
       memory_types=_CALVL, max_version=V4_0),
    _s("calvl_capture", _MC, WIDTH_PER_SLICE, _TR, V3_1,
       "CA training capture strobe (v3.1). Removed in v5.x.",
       memory_types=_CALVL, max_version=V4_0),
    _s("calvl_resp", _PHY, WIDTH_TWO_BITS, _TR, V3_1,
       "CA training response (v3.1: LPDDR3 MR41/MR48 phases; v4.0: "
       "2-bit with LPDDR4 VREF-done encoding). Removed in v5.x.",
       memory_types=_CALVL, max_version=V4_0),
    _s("phy_calvl_cs_n", _PHY, WIDTH_CS, _TR, V3_1,
       "CS the PHY wants CA-trained, active low (v3.1). Renamed "
       "dfi_phy_calvl_cs in v4.0.", memory_types=_CALVL,
       max_version=V3_1),
    _s("phy_calvl_cs", _PHY, WIDTH_RANK, _TR, V4_0,
       "CS under CA training (v4.0 rename). Removed in v5.x.",
       memory_types=_CALVL, max_version=V4_0),
    _s("calvl_ca_sel", _MC, WIDTH_TWO_BITS, _TR, V4_0,
       "CA training foreground pattern strobe (v4.0). Removed in v5.x.",
       memory_types=_CALVL, max_version=V4_0),
    _s("calvl_data", _MC, WIDTH_PER_SLICE, _TR, V4_0,
       "LPDDR4 CA VREF training data (7 bits/slice, v4.0). Removed in "
       "v5.x.", memory_types=frozenset({MemoryType.LPDDR4}),
       max_version=V4_0),
    _s("calvl_done", _MC, WIDTH_ONE_BIT, _TR, V4_0,
       "LPDDR4 CA VREF training done (v4.0). Removed in v5.x.",
       memory_types=frozenset({MemoryType.LPDDR4}), max_version=V4_0),
    _s("calvl_result", _PHY, WIDTH_ONE_BIT, _TR, V4_0,
       "LPDDR4 CA VREF training result (v4.0). Removed in v5.x.",
       memory_types=frozenset({MemoryType.LPDDR4}), max_version=V4_0),
    _s("calvl_strobe", _MC, WIDTH_PER_SLICE, _TR, V4_0,
       "LPDDR4 CA VREF training strobe (v4.0). Removed in v5.x.",
       memory_types=frozenset({MemoryType.LPDDR4}), max_version=V4_0),
    # --- write DQ training (v4.0) ---
    _s("wdqlvl_en", _MC, WIDTH_PER_SLICE, _TR, V4_0,
       "MC enables write DQ training (v4.0; requires 4.0 MC + 4.0 PHY). "
       "Removed in v5.x.", max_version=V4_0),
    _s("wdqlvl_req", _PHY, WIDTH_PER_SLICE, _TR, V4_0,
       "PHY requests write DQ training (v4.0). Removed in v5.x.",
       max_version=V4_0),
    _s("wdqlvl_resp", _PHY, WIDTH_PER_SLICE, _TR, V4_0,
       "Write DQ training response (v4.0). Removed in v5.x.",
       max_version=V4_0),
    _s("wdqlvl_result", _PHY, WIDTH_ONE_BIT, _TR, V4_0,
       "Write DQ training result (v4.0). Removed in v5.x.",
       max_version=V4_0),
    _s("wdqlvl_done", _MC, WIDTH_PER_SLICE, _TR, V4_0,
       "Write DQ training done (v4.0). Removed in v5.x.",
       max_version=V4_0),
    _s("phy_wdqlvl_cs", _PHY, WIDTH_RANK, _TR, V4_0,
       "CS under write DQ training (v4.0). Removed in v5.x.",
       max_version=V4_0),
)

# --------------------------------------------------------------------
# DB training interface (v4.0 only — DDR4 LRDIMM data buffers)
# --------------------------------------------------------------------
DB_TRAINING_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("db_train_en", _MC, WIDTH_ONE_BIT, SubInterface.DB_TRAINING, V4_0,
       "DDR4 LRDIMM data-buffer training enable (PHY evaluation mode). "
       "Removed in v5.x.", memory_types=_DDR4, max_version=V4_0),
    _s("db_train_resp", _PHY, WIDTH_ONE_BIT, SubInterface.DB_TRAINING, V4_0,
       "DDR4 LRDIMM data-buffer training response. Removed in v5.x.",
       memory_types=_DDR4, max_version=V4_0),
)

_LP = SubInterface.LOW_POWER

# --------------------------------------------------------------------
# Low power control interface (v2.1, 20 May 2009 addition)
# --------------------------------------------------------------------
LOW_POWER_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("lp_req", _MC, WIDTH_ONE_BIT, _LP, V2_1,
       "Low-power opportunity request. Split into dfi_lp_ctrl_req + "
       "dfi_lp_data_req in v3.1.", max_version=V2_1),
    _s("lp_ctrl_req", _MC, WIDTH_ONE_BIT, _LP, V3_1,
       "Control-interface low-power request (v3.1 split of dfi_lp_req)"),
    _s("lp_data_req", _MC, WIDTH_ONE_BIT, _LP, V3_1,
       "Data-interface low-power request (v3.1)"),
    _s("lp_ack", _PHY, WIDTH_ONE_BIT, _LP, V2_1,
       "PHY low-power acknowledge (shared). Split into ctrl/data acks "
       "in v5.1.", max_version=V4_0),
    _s("lp_wakeup", _MC, WIDTH_FIVE_BITS, _LP, V2_1,
       "Wakeup-time encoding (shared). Split into ctrl/data wakeups in "
       "v5.1.", max_version=V4_0),
    _s("lp_ctrl_ack", _PHY, WIDTH_ONE_BIT, _LP, V5_2,
       "Control-interface low-power acknowledge (5.1 split of "
       "dfi_lp_ack)"),
    _s("lp_data_ack", _PHY, WIDTH_ONE_BIT, _LP, V5_2,
       "Data-interface low-power acknowledge (5.1)"),
    _s("lp_ctrl_wakeup", _MC, WIDTH_THREE_BITS, _LP, V5_2,
       "Control-interface wakeup-time encoding (5.1 split of "
       "dfi_lp_wakeup)"),
    _s("lp_data_wakeup", _MC, WIDTH_THREE_BITS, _LP, V5_2,
       "Data-interface wakeup-time encoding (5.1)"),
)

_ERR = SubInterface.ERROR

# --------------------------------------------------------------------
# Error interface (v3.0)
# --------------------------------------------------------------------
ERROR_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("error", _PHY, WIDTH_CTRL, _ERR, V3_1,
       "PHY error indicator (v3.0). Renamed dfi_phy_error in v6.0.",
       max_version=V5_2),
    _s("error_info", _PHY, WIDTH_CTRL, _ERR, V3_1,
       "PHY error code, valid with dfi_error (v3.0). Renamed "
       "dfi_phy_error_info in v6.0.", max_version=V5_2),
    _s("phy_error", _PHY, WIDTH_CTRL, _ERR, V6_0,
       "PHY error indicator (v6.0 rename of dfi_error; typically 1 bit "
       "per data slice; not phased for frequency ratio)"),
    _s("phy_error_info", _PHY, WIDTH_CTRL, _ERR, V6_0,
       "PHY error info (v6.0 rename of dfi_error_info; 4 bits per "
       "instance; not phased for frequency ratio)"),
)

_PM = SubInterface.PHY_MANAGED

# --------------------------------------------------------------------
# PHY Master (v4.0) / PHY Managed (renamed v5.2) interface
# --------------------------------------------------------------------
PHY_MANAGED_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("phymstr_req", _PHY, WIDTH_ONE_BIT, _PM, V4_0,
       "PHY requests control of the DFI/DRAM buses (v4.0 'PHY Master'). "
       "Renamed dfi_phymngd_req in v5.2.", max_version=V4_0),
    _s("phymstr_ack", _MC, WIDTH_ONE_BIT, _PM, V4_0,
       "MC grants PHY bus control. Renamed dfi_phymngd_ack in v5.2.",
       max_version=V4_0),
    _s("phymstr_cs_state", _PHY, WIDTH_CS, _PM, V4_0,
       "Per-rank DRAM state during PHY-master operation (with "
       "syscs_state inactive-CS support). Renamed in v5.2.",
       max_version=V4_0),
    _s("phymstr_state_sel", _PHY, WIDTH_ONE_BIT, _PM, V4_0,
       "Selects IDLE vs self-refresh DRAM state. Renamed in v5.2.",
       max_version=V4_0),
    _s("phymstr_type", _PHY, WIDTH_TWO_BITS, _PM, V4_0,
       "PHY-master duration class (tphymstr_type0-3). Renamed in v5.2.",
       max_version=V4_0),
    _s("phymngd_req", _PHY, WIDTH_ONE_BIT, _PM, V5_2,
       "PHY Managed request (v5.2 rename of dfi_phymstr_req)"),
    _s("phymngd_ack", _MC, WIDTH_ONE_BIT, _PM, V5_2,
       "PHY Managed acknowledge (v5.2 rename)"),
    _s("phymngd_cs_state", _PHY, WIDTH_CS, _PM, V5_2,
       "Per-rank DRAM state during PHY-managed operation (v5.2 rename)"),
    _s("phymngd_state_sel", _PHY, WIDTH_ONE_BIT, _PM, V5_2,
       "IDLE vs self-refresh state select (v5.2 rename)"),
    _s("phymngd_type", _PHY, WIDTH_TWO_BITS, _PM, V5_2,
       "PHY Managed duration class (v5.2 rename; tphymngd_type0-3)"),
)

# --------------------------------------------------------------------
# Disconnect protocol (v4.0; removed in v6.0). One signal: the MC
# breaks an in-flight update/PHY-Master handshake and flags whether
# the PHY must stay fully operational (QOS) or not (error).
# --------------------------------------------------------------------
DISCONNECT_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("disconnect_error", _MC, WIDTH_ONE_BIT, SubInterface.DISCONNECT, V4_0,
       "Disconnect type flag: 0 = QOS disconnect (PHY stays fully "
       "operational), 1 = error disconnect. Applies to ctrlupd/phyupd/"
       "phymstr(phymngd) handshakes; NOT low-power or freq-change. "
       "Removed in v6.0.", max_version=V5_2),
)

_MSG = SubInterface.MC_TO_PHY_MSG

# --------------------------------------------------------------------
# MC to PHY message interface (5.1 proposals, in the 5.2 book)
# --------------------------------------------------------------------
MC_TO_PHY_MSG_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("ctrlmsg_req", _MC, WIDTH_ONE_BIT, _MSG, V5_2,
       "Message request (MC to PHY message interface)"),
    _s("ctrlmsg_ack", _PHY, WIDTH_ONE_BIT, _MSG, V5_2,
       "Message acknowledge"),
    _s("ctrlmsg", _MC, WIDTH_EIGHT_BITS, _MSG, V5_2,
       "Message opcode (8 bits)"),
    _s("ctrlmsg_data", _MC, WIDTH_SIXTEEN_BITS, _MSG, V5_2,
       "Message payload (16 bits)"),
)

_WCK = SubInterface.WCK_CONTROL

# --------------------------------------------------------------------
# WCK control interface (5.1 proposals; LPDDR5, +LPDDR6 in v6.0)
# --------------------------------------------------------------------
WCK_CONTROL_SIGNALS: Tuple[SignalSpec, ...] = (
    _s("wck_en", _MC, WIDTH_WCK, _WCK, V5_2,
       "WCK enable (per data slice). Required for LPDDR5/LPDDR6/HBM4 "
       "(v6.0 Table 13; HBM4 from v6.0).", memory_types=_WCK_MEM_ALL),
    _s("wck_toggle", _MC, WIDTH_WCK, _WCK, V5_2,
       "WCK toggle pattern (2 bits per WCK per slice). NOTE: the "
       "LPDDR5 2:1 WCK:CK encoding CHANGED between v5.x and v6.0.",
       memory_types=_WCK_MEM_ALL),
    _s("wck_cs", _MC, WIDTH_WCK, _WCK, V5_2,
       "WCK chip select (per CS per slice); LPDDR5/LPDDR6 multi-CS "
       "only (v6.0 Table 13).", memory_types=_WCK_MEM),
)


ALL_SIGNALS: Tuple[SignalSpec, ...] = (
    COMMAND_SIGNALS + WRITE_DATA_SIGNALS + READ_DATA_SIGNALS
    + UPDATE_SIGNALS + STATUS_SIGNALS + TRAINING_SIGNALS
    + DB_TRAINING_SIGNALS + LOW_POWER_SIGNALS + ERROR_SIGNALS
    + PHY_MANAGED_SIGNALS + DISCONNECT_SIGNALS + MC_TO_PHY_MSG_SIGNALS
    + WCK_CONTROL_SIGNALS
)

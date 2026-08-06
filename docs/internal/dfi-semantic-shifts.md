# DFI Semantic-Shift Catalog (spec-verified)

> **Status:** verified against the actual specification PDFs — DFI
> v2.1.1 (Denali, Jun 2010), v3.1 (Cadence, Mar 2014), v4.0 (Apr 2018),
> v5.2 (Oct 2024), v6.0 (May 2026). The first draft of this document
> was written from release-note hearsay before the PDFs were readable;
> that draft got several load-bearing facts wrong. This revision is the
> corrected record — every claim below traces to a chapter-3 signal
> table or the revision history of one of the books.
>
> **Scope:** DFI v2.1 through v6.0, DDR1-5 / LPDDR1-6 / HBM4 as each
> version defines. The signal-level ground truth lives in
> `dfi_signal_catalog.py`; this doc records the *behavioral* shifts and
> the corrections that came out of the verification pass.

## Corrections from the spec-verification pass (2026-08)

The original draft (and the code built from it) fabricated wires and
misattributed versions. For the record — and so nobody reintroduces
them:

| Fabricated / wrong | Spec reality |
|---|---|
| `dfi_freq_change_req/ack/protocol` | No such wires in any version. Frequency change is `dfi_init_start`/`dfi_init_complete` (v2.1 §4.8; unchanged through v6.0). |
| `dfi_crc_alert` (active high) | `dfi_alert_n` (v3.0+, ACTIVE LOW), renamed `dfi_alert` in v6.0 (polarity follows the memory signal). |
| `dfi_parity_check` | v2.1: `dfi_parity_error`; v3.0+: folded into `dfi_alert_n`. |
| `dfi_training_active` + `dfi_training_phase` | Never existed. Training is per-phase wire groups: `dfi_rdlvl_*`, `dfi_wrlvl_*`, `dfi_calvl_*`, `dfi_wdqlvl_*`, `dfi_db_train_*`. |
| `dfi_disconnect_req/ack` | One wire: `dfi_disconnect_error` (v4.0). A disconnect is the act of *breaking* an in-flight handshake, not a handshake of its own. |
| "Update handshake rewritten in v3.0" | The full bidirectional handshake (`ctrlupd_req/ack` + `phyupd_req/ack/type`) is v2.1 baseline. |
| "Training introduced v3.0" | v2.1 has a full training interface; v3.0 *redesigned* it (dropped the delay-register wires); v5.x *deleted* it. |
| "CA parity introduced v3.0 for DDR4" | `dfi_parity_in`/`dfi_parity_error` are v2.1.1 (DDR3 registered DIMMs). v3.0 extended parity to DDR4 and renamed the error wire `dfi_alert_n`. |
| "v5.2 = v4.0 + chapter-title rename" | v5.x REMOVED the training interface and renamed the wires `dfi_phymstr_*` → `dfi_phymngd_*`. Both change BFM sampling; V5_2 has its own behavior class. |

## The architecture (unchanged; survived verification)

Per-version behavior Strategy classes + a registry:

```python
VERSION_BEHAVIOR = {
    DFIVersion.V2_1: DFIv2_1Behavior,
    DFIVersion.V3_1: DFIv3_1Behavior,   # v3.0+v3.1 collapsed
    DFIVersion.V4_0: DFIv4_0Behavior,
    DFIVersion.V5_2: DFIv5_2Behavior,   # v5.0/5.1/5.2 collapsed
    DFIVersion.V6_0: DFIv6_0Behavior,
}
```

Behavior classes are stateless; methods take `(bus, state)` and return
event objects. Signal *presence* is the envelope's job
(`dfi_signals.py` + `dfi_signal_catalog.py`, `min_version`/
`max_version` per signal); behavior classes own the *meaning* of wires
that exist under the same concept across versions.

Two additions the verification forced:

- `RemovedInThisVersionError` (subclass of
  `NotSupportedInThisVersionError`): the spec doesn't only add
  interfaces — v5.x deleted training, v6.0 deleted disconnect.
- A `low_power()` behavior area: the LP handshake exists from v2.1 and
  shifts twice (v3.1 ctrl/data request split; v5.1 ctrl/data ack +
  wakeup split).

## Shift areas (spec-verified)

### 1. CRC / alert

- **v2.1:** no CRC concept → raises.
- **v3.0:** DDR4 write CRC; errors reported on `dfi_alert_n` (active
  LOW, mirrors DDR4 ALERT_n). CRC and CA-parity errors share the wire
  and are **indistinguishable at the DFI**.
- **v4.0:** `phycrc_mode` parameter (MC- vs PHY-generated CRC); same
  wire.
- **v5.2:** adds Link DQ CRC for DDR5 MRDIMM Mux Mode
  (`dfi_wrdata_crc` / `dfi_rddata_crc`, `phylinkdqcrc_mode`).
- **v6.0:** wire renamed `dfi_alert`, polarity per memory protocol;
  `dfi_data_alert` added for protocols with separate write-error paths
  (HBM4).

### 2. Update interface

- **v2.1:** full bidirectional handshake already present:
  `dfi_ctrlupd_req/ack` (PHY may ignore) and `dfi_phyupd_req/ack`
  (MC MUST ack within `tphyupd_resp`), with `dfi_phyupd_type`
  selecting one of 4 duration classes. Simultaneous requests: either
  side may ack the other; the un-acked request may de-assert.
- **v3.0:** idle-bus definition tightened; enhancements only.
- **v4.0:** a ctrlupd handshake is REQUIRED immediately before
  self-refresh exit; `tctrlupd_interval` bounds request cadence.
- **v6.0:** unchanged wires.

### 3. PHY Master / PHY Managed

- **v4.0:** introduced as PHY Master: `dfi_phymstr_req/ack` plus
  qualifiers `type` (duration class `tphymstr_type0-3`), `state_sel`
  (IDLE vs self-refresh), `cs_state` (per-rank DRAM state), with
  `syscs_state` inactive-CS support.
- **v5.2:** renamed PHY Managed — **the wires renamed too**
  (`dfi_phymngd_*`). Same protocol; a v5.2 BFM samples different
  signal names (handled via the `_takeover_prefix` class attribute).
- **v6.0:** unchanged from v5.2; now also the designated home of all
  training (PHY Independent Mode).

### 4. Disconnect protocol

- **v4.0-v5.x:** a device breaks an in-flight ctrlupd / phyupd /
  training / phymstr handshake (LP and freq-change are explicitly NOT
  disconnectable). One dedicated wire: `dfi_disconnect_error`
  (0 = QOS, PHY stays fully operational; 1 = error). Timing bounded by
  per-interface `t*_disconnect` / `t*_disconnect_error` pairs.
- **v6.0:** REMOVED → raises `RemovedInThisVersionError`.

### 5. Frequency change

Same protocol in every version — `dfi_init_start` asserted during
normal operation is the request; the PHY **accepts by de-asserting
`dfi_init_complete`** within `tinit_start` cycles, or the offer is
withdrawn ("Not Acknowledged"). What changes is the indicator payload:

- **v2.1:** `dfi_freq_ratio` (2 bits: 1:1 / 1:2 / 1:4).
- **v4.0:** `dfi_frequency` indicator (5 bits, system-defined
  encodings, `phyfreq_range`).
- **v5.1/5.2:** `dfi_freq_fsp`; `dfi_frequency` to 6 bits; v5.2 splits
  `dfi_freq_ratio` → `dfi_cmd_freq_ratio` + `dfi_data_freq_ratio`
  (adds 1:8; backward compat = cmd ratio 'b00).
- **v6.0:** ratios gain 1:3 and 1:6; 3-bit encodings.

### 6. Training

- **v2.1:** read leveling + gate training (DDR3/LPDDR2) and write
  leveling (DDR3): en/req/resp handshakes PLUS a delay-register
  protocol (`dfi_rdlvl_delay_X` / `_load` / `_edge`, MC vs PHY
  evaluation modes).
- **v3.0:** redesign — delay-register wires and MC evaluation mode
  dropped; en/req/resp kept; per-CS training targets
  (`dfi_phy_*lvl_cs_n`); `dfi_lvl_pattern` / `dfi_lvl_periodic`.
- **v3.1:** CA training for LPDDR3 (`dfi_calvl_*`); PHY-requested
  training (`dfi_phylvl_req_cs_n` / `dfi_phylvl_ack_cs_n`).
- **v4.0:** optional per-operation (PHY Independent Mode); per-slice
  read leveling; write DQ training (`dfi_wdqlvl_*`); DB training
  (DDR4 LRDIMM); LPDDR4 CA VREF training; `*_cs_n` → `*_cs` renames.
- **v5.x:** **interface deleted.** "The DFI specification does not
  dictate any training methodology." → `RemovedInThisVersionError`.
- **v6.0:** stays deleted.

### 7. Error interface

- **v3.0:** `dfi_error` + `dfi_error_info` (implementation-defined
  codes).
- **v6.0:** renamed `dfi_phy_error` / `dfi_phy_error_info` (per data
  slice, not phased for frequency ratio).

### 8. CA parity

- **v2.1.1:** `dfi_parity_in` (MC-computed) + `dfi_parity_error`
  (PHY-reported) for DDR3 registered DIMMs → `CAParityEvent`.
- **v3.0:** `dfi_parity_error` → `dfi_alert_n`; parity errors merge
  with CRC reporting (surface as `CRCEvent`; `ca_parity_check()`
  returns None to avoid double-reporting).
- **v6.0:** `dfi_parity_in` → `dfi_caparity`; errors on `dfi_alert`.

### 9. Low power control

- **v2.1:** `dfi_lp_req` + `dfi_lp_wakeup` (MC offer) / `dfi_lp_ack`.
- **v3.1:** request split: `dfi_lp_ctrl_req` + `dfi_lp_data_req`
  (shared ack + wakeup).
- **v5.1:** ack and wakeup split too: `dfi_lp_ctrl_ack` /
  `dfi_lp_data_ack`, `dfi_lp_ctrl_wakeup` / `dfi_lp_data_wakeup`
  (3-bit encodings, `dfilp_*_wakeup_map` parameters in v6.0).
- Explicitly NOT disconnectable (v4.0+).

### 10. v6.0 new areas (not yet behavior-mapped)

- **Sleep protocol:** `dfi_sleep` + `tsleep_*` family (explicitly not
  applicable to 5.x parts). Candidate for a new behavior area when a
  v6 testbench needs it.
- **Command bus enable** (`dfi_cmd_en`), parity/ECC/severity data-path
  buses (`dfi_wrparity` / `dfi_rdparity(_valid)` / `dfi_wrdata_ecc` /
  `dfi_rddata_ecc` / `dfi_rddata_sev`), MRDIMM Mux-Mode pseudo-channel
  interleave.
- **Interop hazard:** the LPDDR5 2:1 WCK:CK `dfi_wck_toggle` encoding
  CHANGED between 5.x and 6.x (v6.0 Table 34 footnote).

## Known spec typos (recorded, not "fixed" silently)

- v5.2 Table prints `dfi_rddata_crc` as From=MC; body text says the
  PHY drives it. The catalog encodes PHY (read path).
- v4.0 carries editorial leftovers ("adeela: verify" in a default
  cell); v2.1 figures label `dfi_bank` as `dfi_bank_n`.
- v3.1 is inconsistent on the `dfi_phylvl_*` width name (Rank vs Chip
  Select width).

## Testing

- Behavior classes: one unit-test file each
  (`tests/unit/behaviors/test_{base,v3_1,v4_0,v5_2,v6_0}.py`) with a
  mock bus. Active-low wires (`alert_n`, `phylvl_req_cs_n`) idle at 1
  in the mock.
- Envelope: `tests/unit/test_dfi_signals.py` asserts version windows,
  renames, and removals against the catalog.
- Wire-level proofs: `tests/sim/dfi/` over the `dfi_shim.sv`
  passthrough (spec-real wires only).

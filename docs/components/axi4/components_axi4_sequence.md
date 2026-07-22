<!-- RTL Design Sherpa Documentation Header -->
<table>
<tr>
<td width="80">
  <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">
    <img src="https://raw.githubusercontent.com/sean-galloway/RTLDesignSherpa/main/docs/logos/Logo_200px.png" alt="RTL Design Sherpa" width="70">
  </a>
</td>
<td>
  <strong>CocoTB Framework</strong> · <em>Verification Infrastructure for RTL Testing</em><br>
  <sub>
    <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">GitHub</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/docs/DOCUMENTATION_INDEX.md">Documentation Index</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/LICENSE">MIT License</a>
  </sub>
</td>
</tr>
</table>

---

<!-- End Header -->

# axi4_sequence.py

Authored-once, run-many sequence layer for the AXI4 BFM. Each entry is data (an
`AXI4Burst`), and a single async runner walks the list against `AXI4MasterWrite` /
`AXI4MasterRead`. Mirrors the `GAXISequence` pattern, with DDR/SDRAM-aware helpers
for building controller-stress traffic.

## Overview

The `AXI4Sequence` class provides:
- **Declarative bursts** — build a list of read/write transactions up front, then run them.
- **Bus-width aware** — `AWSIZE`/`ARSIZE` are derived from `data_width`; one sequence serves any bus.
- **DDR/SDRAM stress patterns** — row-hit, bank-spray, and row-miss helpers that exercise a memory controller's scheduler (PRE/ACT, tFAW/tRRD).
- **Randomized workloads** — weighted burst sizes, write/read ratio, QoS and ID pools, address alignment.
- **Tagging + filtering** — every burst carries a `tag`; `filter()` builds a sub-sequence (e.g. to exclude a buggy pattern).
- **Single async runner** — `run_axi4_sequence()` drives the bursts against the BFM masters and returns per-burst results.

A sequence holds only *data*; nothing touches the DUT until `run_axi4_sequence()` is awaited.

## Data Model

### `AXI4Burst`

Dataclass describing one burst. Sequence helpers populate it; you rarely build one by hand.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `is_write` | `bool` | — | `True` = write, `False` = read |
| `addr` | `int` | — | Start byte address |
| `length` | `int` | — | Beats in the burst (1..256; maps to A*LEN = length − 1) |
| `axid` | `int` | `0` | Transaction ID (AWID/ARID) |
| `qos` | `int` | `0` | Quality-of-service (AWQOS/ARQOS) |
| `size` | `int` | `3` | A*SIZE = log2(bytes/beat); set automatically from `data_width` |
| `burst_type` | `int` | `1` | A*BURST — 0=FIXED, 1=INCR, 2=WRAP |
| `data` | `Optional[List[int]]` | `None` | Per-beat write data (`None` for reads) |
| `strb` | `int` | `0xFF` | WSTRB applied to every beat |
| `delay_cycles` | `int` | `0` | Idle clock cycles before this burst |
| `tag` | `Optional[str]` | `None` | Debug label identifying which helper created it |

> **Note:** `strb` defaults to `0xFF` (all bytes on a 64-bit bus). On a non-64-bit bus, pass an explicit `strb` that matches `bytes_per_beat` (e.g. `0xF` for 32-bit, `0xFFFF` for 128-bit).

## Class

### `AXI4Sequence`

```python
AXI4Sequence(
    name: str = "seq",
    *,
    data_width: int = 64,
    id_width: int = 4,
    addr_width: int = 32,
    seed: Optional[int] = None,
)
```

**Parameters:**
- `name` — label used in `__repr__` and messages.
- `data_width` — bus width in bits; sets `bytes_per_beat = data_width // 8` and the `size` of every helper-built burst.
- `id_width` / `addr_width` — recorded on the sequence (carried through `filter()`); not used for internal masking.
- `seed` — seeds the internal RNG for reproducible randomized workloads and `shuffle()`.

**Attributes:**
- `bursts: List[AXI4Burst]` — the ordered list (iterable via `len(seq)` / `for b in seq`).
- `bytes_per_beat: int` — `data_width // 8`.
- `stats: Dict[str, int]` — counters: `writes`, `reads`, `row_hit_bursts`, `bank_spray_bursts`, `row_miss_pairs`, `random_bursts`. (`writes`/`reads` count *all* bursts; the category keys are overlapping breakdowns.)

## Core Methods

### Basic Transactions

#### `add_write(addr, data, *, axid=0, qos=0, delay=0, tag=None) -> int`

Append one write burst. A scalar `data` is wrapped to a single-beat list; `length = len(data)`.

**Returns:** index of the new burst in `seq.bursts`.

```python
seq.add_write(0x1000, [0xDEAD, 0xBEEF], axid=2, tag="hdr")
```

#### `add_read(addr, length=1, *, axid=0, qos=0, delay=0, tag=None) -> int`

Append one read burst of `length` beats.

**Returns:** index of the new burst.

```python
seq.add_read(0x1000, length=2, axid=2)
```

### DDR/SDRAM-Aware Patterns

These build traffic that exercises a memory controller's scheduler.

#### `add_row_hit_burst(base_addr, n_followups, *, burst_bytes=64, col_increment_bytes=None, is_write=True, qos=0, axid=0, data_fn=None, tag="row_hit") -> List[int]`

A base burst plus `n_followups` bursts that **increment the column only** (`col_increment_bytes` defaults to `burst_bytes`). If the controller's address map keeps row+bank fixed under the increment, every follow-up is a **row hit** — the scheduler must *not* issue PRE/ACT. Beats per burst = `max(1, burst_bytes // bytes_per_beat)`.

**Returns:** list of burst indices (`n_followups + 1`).

#### `add_bank_spray(base_addr, num_banks=8, *, bank_stride_bytes=0x400, burst_bytes=64, is_write=True, qos=0, axid=0, data_fn=None, tag="bank_spray") -> List[int]`

`num_banks` bursts at `base_addr + b * bank_stride_bytes`, same row across banks — exercises the **tFAW / tRRD** windows.

**Returns:** list of burst indices.

#### `add_row_miss_pair(base_addr, *, row_stride_bytes=0x2000, burst_bytes=64, is_write_first=True, is_write_second=True, qos=0, axid=0, tag="row_miss") -> Tuple[int, int]`

Exactly two bursts — one at `base_addr`, one at `base_addr + row_stride_bytes` — to the same bank but a **different row**, forcing **PRE → ACT** between them. Each burst's write/read direction is independent.

**Returns:** `(idx0, idx1)`.

### Random Workload

#### `add_random_workload(count, *, addr_range=(0, 0x10000), write_ratio=0.6, size_weights=None, qos_choices=None, id_choices=None, align_to=None, data_fn=None, tag="random") -> List[int]`

Append `count` randomized bursts.

**Parameters:**
- `addr_range` — `(lo, hi)` byte window.
- `write_ratio` — fraction of writes (default 0.6 → 60/40 W:R).
- `size_weights` — `{burst_bytes: weight}`; default `{128: 0.2, 256: 0.2, 512: 0.4, 1024: 0.2}`.
- `qos_choices` / `id_choices` — pools to draw QoS/ID from (default `[0]`).
- `align_to` — alignment in bytes; defaults to the largest size in `size_weights`.
- `data_fn` — optional `f(addr, idx) -> int` for custom write data.

**Returns:** list of burst indices.

> **Tip:** keep `addr_range[0]` aligned to `align_to`; otherwise alignment can pull a low address toward the bottom of the window.

### Sequence Management

#### `reset() -> None`
Clear all bursts and zero the stats.

#### `filter(predicate) -> AXI4Sequence`
Return a **new** sequence (name suffixed `_filtered`) containing only bursts where `predicate(burst)` is `True`. The original is unchanged. Useful for excluding a tag:

```python
clean = seq.filter(lambda b: b.tag != "row_miss")
```

> The filtered copy's `stats` are recomputed from the surviving bursts (category counters are best-effort, based on the default helper tags).

#### `shuffle() -> AXI4Sequence`
Shuffle the bursts **in place** using the sequence RNG (reproducible with `seed`) and return `self` for chaining. (Note the asymmetry: `filter()` returns a new sequence, `shuffle()` mutates.)

#### `__len__` / `__iter__` / `__repr__`
Standard container interface; `repr` reports name and write/read counts.

## Running a Sequence

### `run_axi4_sequence(seq, *, master_wr=None, master_rd=None, log=None, on_burst=None, raise_on_error=False) -> List[Dict]`

Async runner that walks the sequence **sequentially** (one burst at a time, no pipelining) against the BFM masters.

**Parameters:**
- `seq` — the `AXI4Sequence` to run.
- `master_wr` — an `AXI4MasterWrite` (required if the sequence contains writes).
- `master_rd` — an `AXI4MasterRead` (required if the sequence contains reads).
- `log` — optional logger (`.info()` / `.error()`).
- `on_burst` — optional callback `f(idx, burst, result)` invoked after each burst; both sync and async callbacks are accepted.
- `raise_on_error` — when `True`, re-raise any per-burst errors as a single `RuntimeError` after the sequence completes. Recommended for tests that would otherwise read only `result["data"]` and silently discard `result["error"]`.

**Behavior:**
- Derives the clock from `master_wr` (else `master_rd`) and honors each burst's `delay_cycles` with `RisingEdge`.
- Writes call `master_wr.write_transaction(...)`; reads call `master_rd.read_transaction(...)` and capture returned data. A write whose result dict reports `success=False` is surfaced as that burst's `error`.
- Raises `RuntimeError` if a write is encountered with no `master_wr` (or a read with no `master_rd`).
- The `RisingEdge` import is lazy — call it inside a running cocotb simulation.

**Returns:** a list of per-burst result dicts with keys: `is_write`, `addr`, `length`, `axid`, `qos`, `tag`, `data`, `error`.

### `run_axi4_sequence_engine(seq, *, master_wr=None, master_rd=None, log=None, timeout_cycles=1_000_000, raise_on_error=False) -> List[Dict]`

Engine-style runner with the same return contract as `run_axi4_sequence`. Instead of walking bursts sequentially (per-burst lock + response wait), it queues every AW/W/AR packet back-to-back at the channel level and collects B/R responses asynchronously — reproducing the bus behavior of the pattern-gen/CRC-check RTL engines (one AW per cycle when ready). Writes are issued first, then reads.

> Not re-exported by the package `__init__` — import it from the module directly:
> `from CocoTBFramework.components.axi4.axi4_sequence import run_axi4_sequence_engine`

```python
from CocoTBFramework.components.axi4 import AXI4Sequence, run_axi4_sequence

results = await run_axi4_sequence(seq, master_wr=m_wr, master_rd=m_rd, log=log)
errors = [r for r in results if r["error"]]
```

## Usage Patterns

### Basic read-after-write

```python
from CocoTBFramework.components.axi4 import AXI4Sequence, run_axi4_sequence

seq = AXI4Sequence("smoke", data_width=64)
seq.add_write(0x1000, [0xA5A5_0000, 0xA5A5_0001], axid=1)
seq.add_read(0x1000, length=2, axid=1)

results = await run_axi4_sequence(seq, master_wr=m_wr, master_rd=m_rd, log=log)
```

### Row-hit stream (scheduler should keep the row open)

```python
seq = AXI4Sequence("row_hits", data_width=64, seed=1)
seq.add_row_hit_burst(0x2_0000, n_followups=7, burst_bytes=64)   # 8 bursts, column-only increments
await run_axi4_sequence(seq, master_wr=m_wr, log=log)
```

### Bank spray + row miss (PRE/ACT pressure)

```python
seq = AXI4Sequence("bank_stress", data_width=64, seed=2)
seq.add_bank_spray(0x0, num_banks=8, bank_stride_bytes=0x400)    # tFAW/tRRD
seq.add_row_miss_pair(0x4_0000, row_stride_bytes=0x2000)         # PRE -> ACT
await run_axi4_sequence(seq, master_wr=m_wr, log=log)
```

### Randomized workload, then exclude a tag

```python
seq = AXI4Sequence("random", data_width=64, seed=42)
seq.add_random_workload(200, addr_range=(0, 0x10000), write_ratio=0.6)

# Drop a pattern that trips a known DUT bug:
clean = seq.filter(lambda b: b.tag != "row_miss")
await run_axi4_sequence(clean, master_wr=m_wr, master_rd=m_rd, log=log)
```

## Best Practices

1. **Match `data_width` to the bus.** It drives `size`; also pass a `strb` that matches `bytes_per_beat` on non-64-bit buses.
2. **Set `seed`** for reproducible randomized/shuffled sequences when triaging failures.
3. **Provide both masters** when a sequence mixes reads and writes — the runner raises if the needed master is missing.
4. **Use `tag` + `filter()`** to carve out problem patterns instead of hand-editing burst lists.
5. **Inspect the returned results** (`r["error"]`, `r["data"]`) rather than relying on the run completing — and pass a `log` so failures are recorded.

---

`AXI4Sequence` keeps stimulus declarative and re-runnable: author the bursts once, tag them, filter as needed, and drive them through the AXI4 BFM with a single awaited runner.

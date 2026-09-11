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

# wb4_sequence.py

`WB4Sequence` is the **traffic** axis for Wishbone B4: what transfers a test
performs, independent of who drives them (`WB4Master`) and when
(`FlexRandomizer`). It is a builder that produces a list of single-beat
transactions, which you can filter, shuffle, replay and convert to packets.

## Why a builder, not parallel lists

The older `APBSequence` shape carries a list per field and walks them with
cycling iterators. `WB4Sequence` follows `AXI4Sequence` instead: methods that
append transfers, so a workload reads as what it does. It is also smaller
than either, because Wishbone has less to describe. A B4 transfer is always
one word -- the registered-feedback bursts of chapter 4 are a HINT carried on
each transfer, not a multi-beat transaction, so there is no burst length to
describe. It has no protection bits, so there is no `prot`. And the
termination status is the slave's answer, never part of the stimulus.

## Construction

```python
from CocoTBFramework.components.wb4.wb4_sequence import WB4Sequence

seq = WB4Sequence("smoke", addr_width=32, data_width=32, seed=1)
```

`sel_width` defaults to `data_width // 8`. Passing `seed` makes the sequence
reproducible, and the sequence owns its own `random.Random`, so building one
never perturbs any other randomisation in the test.

## Primitives

| Method | Effect |
| --- | --- |
| `add_write(addr, data, sel=None, tag="")` | One write; `sel` defaults to every byte |
| `add_read(addr, tag="")` | One read; reads carry an all-ones select |

Addresses and data are masked to the configured widths, so a value too wide
for the bus is truncated where you can see it rather than inside a driver.

## Patterns

| Method | Shape |
| --- | --- |
| `add_block(base, count, we=, stride=, data=)` | A run of transfers one word apart; `data` cycles |
| `add_readback_pairs(base, count)` | Write/read pairs on the same address, so each read has an unambiguous expected value |
| `add_strobed_writes(base, count)` | Full write, partial write, read back: makes a dropped `SEL` visible |
| `add_random_workload(count, ...)` | A random mix, optionally steered at address windows |

### Address windows are the Wishbone-flavoured part

A B4 slave may answer `ERR` or `RTY`, and a test usually provokes those by
aiming at ranges the device under test decodes that way. `windows` takes
`(lo, hi, probability)` triples:

```python
seq.add_random_workload(
    200, addr_lo=0, addr_hi=0xD000, write_frac=0.6,
    windows=[(0xE000, 0xEFFF, 0.1),      # the DUT's ERR range
             (0xF000, 0xFFFF, 0.1)])     # the DUT's RTY range
```

Each transfer drawn from a window is tagged `"rand:w0"`, `"rand:w1"` and so
on, so a scoreboard can tell which range an address came from without
re-deriving the decode. Probabilities are taken in order and must sum to at
most 1.0; the remainder is drawn from `[addr_lo, addr_hi)`.

`unique_addrs=True` refuses to repeat an address within the call, which is
what a test wants when several transfers are in flight and a per-address
model would otherwise race itself.

## Burst hints

`assign_burst_hints()` lays a registered-feedback pattern over the transfers
already built: runs of `INCR` closed by one `EOB`, with classic transfers
between them, one `BTE` held for the length of each run.

```python
seq.add_random_workload(200, addr_hi=0xD000)
seq.assign_burst_hints(burst_frac=0.4, min_len=2, max_len=5)
```

| Argument | Effect |
| --- | --- |
| `burst_frac` | Chance a classic transfer starts a burst (default 0.4) |
| `min_len`, `max_len` | Burst length in transfers, inclusive (default 2..5) |
| `bte_choices` | Which burst types to draw from (default all four) |

A burst that would run off the end of the sequence is closed on the last
transfer, so a sequence never ends mid-burst. `clear_burst_hints()` puts
every transfer back to CLASSIC/LINEAR, which is what a DUT built without the
hints must show on its bus whatever it was handed -- that pair is how a test
checks a `USE_BURST_HINTS` parameter both ways.

The hints are advisory. Nothing in the framework or the RTL library acts on
one, so the pattern only has to be varied and self-describing. What it
proves is that each hint arrives WITH its own transfer rather than a
neighbour's, which is why every run holds one `BTE` and the lengths vary.

## Shaping and output

| Method | Effect |
| --- | --- |
| `filter(predicate)` | A **new** sequence of the matching transfers; the original is untouched |
| `shuffle()` | In place, using the sequence's own generator, so a seeded shuffle repeats |
| `reset()` | Drops every transfer and re-seeds, so the same calls rebuild an identical sequence |
| `to_packets(master=None)` | `WB4Packet` objects ready for `master.send()` |
| `clear_burst_hints()` | Every transfer back to CLASSIC/LINEAR |
| `stats` | `total`, `writes`, `reads`, `unique_addrs`, `partial_writes`, `burst_transfers`, `burst_ends` |

`to_packets(master=...)` compares the sequence's widths against the BFM's and
raises on a mismatch, so a sequence built for the wrong bus is caught rather
than silently truncating an address.

## Full example

```python
seq = WB4Sequence("mixed", addr_width=32, data_width=32, seed=7)
seq.add_readback_pairs(0x1000, 8)
seq.add_strobed_writes(0x2000, 4)
seq.add_random_workload(100, addr_hi=0xD000,
                        windows=[(0xE000, 0xEFFF, 0.1)])
seq.assign_burst_hints()

for pkt in seq.to_packets(master):
    await master.send(pkt)
await master.wait_idle()
```

## Navigation
- [**Back to Wishbone B4 Index**](components_wb4_index.md)
- [**Back to Components**](../components_index.md)

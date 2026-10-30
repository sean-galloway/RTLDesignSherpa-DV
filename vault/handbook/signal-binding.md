---
title: Every family binds through SignalResolver
summary: A BFM that is not a GAXI composition still resolves its pins with the shared SignalResolver (a "flat" config), never a private prefix + name binder. CXS and the first CHI cut did the latter and every differently spelled port needed a hand-written signal_map.
---

# Every family binds through SignalResolver

`components/shared/signal_mapping_helper.py` is the one place that knows how
a DUT may spell a pin: `prefix` and `bus_name` with or without a trailing
underscore, the alternative spellings per logical signal, upper-case spec
names, and a partial `signal_map` override with typo rejection. A family
that resolves its own pins forfeits all of that at once.

**The rule: a new family registers a `PROTOCOL_SIGNAL_CONFIGS` entry (and
the matching `PROTOCOL_TYPES` identifier, see
`tests/unit/test_protocol_registry_parity.py`) and constructs a
`SignalResolver`. It does not walk `dir(dut)` itself.**

## Case study, 2026-10-30

CXS (IHI 0079) and the first CHI (IHI 0050) cut each shipped with a private
binder: `prefix + lower-case name`, case-insensitive, `signal_map` as a
whole-name override. It looked adequate because both families' own tests
used ports named exactly that way. The owner's experience was the opposite:
a port spelled `crd_gnt`, `tx_req_flit_v` or `CXSCRDGNT` needed a
`signal_map` entry per signal, "overriding signals all day long", which is
precisely the chore the resolver exists to remove. Ruling: both families
bind through the resolver, and so does every family after them.

## The flat config kind

Credited-flit protocols have no valid/ready pair and no single data signal,
so the resolver's GAXI-shaped layering (`i_valid` / `o_ready`, `multi_sig`,
the mandatory `data_sig`) does not fit. Rather than extend the per-protocol
if-chains, a config may carry `'flat': True`:

- every key of `signal_map` (required) and `optional_signal_map` (optional)
  IS the logical name a component asks for with `resolver.get_signal(name)`;
- `signal_map` given to the component uses those same keys;
- `_validate_required_signals` does not demand a data signal.

`cxs_signal_config()` and `chi_signal_config(node)` build the entries from
spelling tables; `tests/unit/test_flat_signal_resolver.py` pins the
spellings against a fake DUT, so a new spelling is one row in a table plus
one test line.

## Sides are not a knob

CHI names every signal from the node that owns the port, and RSP / DAT run
both ways, so a port has a `txrspflitv` AND an `rxrspflitv`. The first cut
exposed a `dut_perspective` flag to say which one was "mine". That was a
smell: a real DUT always names its own outputs `tx`, so a BFM always drives
the DUT's `rx*` and samples its `tx*`, the same way an AXI master always
drives the slave's `aw*`. The flag only existed because the loopback DUT
was named from each BFM's own side. Fixed by naming the loopback's sides
the way the node across from them would; the flag is gone and a CHI port
binds with a prefix and nothing else.

See [[spec-fidelity]] for where the signal names themselves come from.

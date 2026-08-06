# Known issue: ACK-mode arbiter compliance loses a grant

> **Status:** open, P2. Filed 2026-08-05 alongside the fix for three related
> defects in the same model. The **no-ACK path is clean** and is asserted on by
> the consuming testbenches; this is `WAIT_GNT_ACK=1` only.
>
> **Issue:** [#50](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/50)
> **Component:** `src/CocoTBFramework/components/shared/arbiter_compliance.py`
> **Tracked downstream as:** COMMON-019 (RTLDesignSherpa, `vault/Tasks/common/`)

## What happens

Two residuals in the ACK path of `ArbiterCompliance`.

### 1. `round_robin_violation`, roughly 3 runs in 8

Reproduces on `val/common/test_arbiter_round_robin.py` config `[4-1]`
(`CLIENTS=4`, `WAIT_GNT_ACK=1`) at `REG_LEVEL=GATE`. Every surviving violation
has the same shape — the RTL granted a client *further along* the rotation than
the model expected:

    expected 0, got 1: requests=0x3, mask=0x0, last_winner_at_grant=3
    expected 1, got 2: requests=0x7, mask=0xe, last_winner_at_grant=0

In both, the arbiter behaves as if its last winner were one grant ahead of the
model's. That points at the model **missing a grant**, not the arbiter
misrotating.

Prime suspect is `is_new_grant` in `_check_round_robin_compliance_ack_mode`:

```python
existing_pending = [t for t, c in self.pending_acks.items() if c == current_winner]
is_new_grant = not existing_pending
```

It is re-derived from `pending_acks` rather than read from the transaction's own
`transaction_type`, which the monitor already sets (`new_grant` vs
`grant_continuation`). A grant to a client that still owes an ACK is therefore
skipped entirely — no compliance check *and* no mask update.

### 2. `unexpected_ack` during single-client saturation

115-150 per run on `c08_w1` and `c16_w1` at `REG_LEVEL=FULL`. All land in the
single-client saturation phase, where one client is granted repeatedly: more ACK
edges are observed than grants are registered. `_process_ack_mode_grants`
reports `new_grant` on the rising edge and `grant_continuation` thereafter, and
only the former registers a pending ACK. Warning severity, so nothing fails.

## Suggested work

1. Make the ACK path register every grant it is handed — or have `is_new_grant`
   read `transaction.metadata['transaction_type']` instead of re-deriving it
   from `pending_acks` — then re-measure over >= 8 runs of `[4-1]`.
2. Reconcile grant/ACK counting for held grants so saturation stops emitting
   `unexpected_ack`.
3. When both are clean, drop the `WAIT_GNT_ACK == 1` early return in
   `arbiter_round_robin_tb.check_monitor_errors()` downstream so ACK mode
   asserts the way no-ACK does.

## Context: what was already fixed

Three defects in this model were fixed in the same pass. All three made a
**correct** arbiter look broken, which is the prior worth holding when this
model reports a violation:

- **Wrong request vector.** The check was always paired with the previous
  cycle's requests — correct for a registered grant, wrong for a combinational
  one, and worth 144-176 bogus violations per run on `arbiter_round_robin_simple`.
  Now selected by the `registered_grant` constructor argument.
- **No `r_last_valid` mirror.** Two grant-less cycles drop the RTL's priority
  mask back to reset; the model carried its pre-idle winner across the gap and
  reported a violation on the first grant after every `block_arb` interval.
- **ACKs processed live against a replay-built table.** `pending_acks` is only
  written while replaying the queue, so an ACK handled at sample time saw a
  table that did not yet contain its own grant. ACKs are now queued via
  `queue_ack` and replayed in one timestamp-ordered stream with the grants.

## Two traps for whoever picks this up

**The mask state advances during replay, not live.** Grants are queued and
`run_compliance_analysis` walks that queue later. Anything you change from the
monitor's sampling loop touches state the replay re-derives and changes
nothing — the first attempt at the `r_last_valid` fix did exactly that, ran
clean, and had zero effect on the violation.

**The replay cannot see cycles, only grants.** Idle counts must be measured by
the sampling loop and handed over (`idle_before`). Inferring them from
transaction timestamps looks equivalent and is not: that inference produced
40-60 false violations per run.

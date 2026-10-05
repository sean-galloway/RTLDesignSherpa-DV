# ACK-mode arbiter compliance: the model lost grants and miscounted ACKs

> **Status:** FIXED. Defect 1 on 2026-08-07 (`ee0aa9c`, closed #50);
> defects 2 and 3 on 2026-10-04 (this entry). The **no-ACK grant path was
> always clean**; defect 3 affected the verdict in both modes.
>
> **Issue:** [#50](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/50)
> **Component:** `src/CocoTBFramework/components/shared/arbiter_monitor.py`,
> `arbiter_compliance.py`
> **Tracked downstream as:** RTLDesignSherpa `vault/Tasks/common/bug/closed/BUG-009.md`
> (legacy id COMMON-019)
> **Regression tests:** `tests/unit/test_arbiter_monitor_ack_mode.py`,
> `tests/unit/test_arbiter_compliance.py`

## What happened

Three defects. All were the model's own; the RTL was correct in every case.

### 1. `round_robin_violation`, roughly 3 runs in 8 -- fixed 2026-08-07

`_ack_mode_state[i]['grant_active']` was cleared only when `grant_valid` FELL.
An arbiter that hands the grant straight from one client to the next never
lowers `grant_valid`, so the old owner's flag stayed `True`; its next grant
failed the rising-edge test, was tagged `grant_continuation`, and the
compliance model skipped it -- no check and no mask update. The model fell
one grant behind the RTL and every later grant read as "expected N, got N+1".
A hand-off now retires the old owner, and `is_new_grant` reads the
transaction's own tag instead of re-deriving it from `pending_acks`.

### 2. `unexpected_ack` whenever one client was granted back-to-back -- fixed 2026-10-04

The 2026-08-07 close reported both symptoms at zero. That was measured on
`arbiter_round_robin`, whose Rule 3 drops `grant_valid` for one cycle after an
ACK when only the owner is still requesting -- so on that arbiter a client is
never granted on consecutive samples, and the path below was never exercised.

`arbiter_round_robin_simple_ack` re-arbitrates on the ACK cycle and, if the
same client is the only requester, grants it again with `grant_valid` held and
the grant vector unchanged. The monitor recognised a new grant only on a
rising edge of "this client holds the grant", and an ACK merely cleared
`waiting_for_ack`: nothing re-armed the detector. Result, in one
single-requester window: 1 `new_grant`, 5,001 continuations, **5,009
`unexpected_ack`** against 5,002 grants. Because the testbench counts progress
in `new_grant` transactions, the window also ran to its 10,000-cycle cap
instead of its 1,000-grant target. Warning severity, so nothing failed and
nobody looked.

A second defect sat in the same path: ACK was treated as an **edge**
(`ack_vector` changed and nonzero). The DUT samples ACK every cycle, so an ACK
level held across back-to-back grants acknowledges each of them at the DUT
and only the first at the monitor.

**The fix**, in `_process_ack_mode_grants` / `_process_grant_changes` /
`_process_ack_changes`:

- An ACK sampled with the grant it answers retires that grant. Whatever is
  granted on the next sample is a new grant, even when the vector did not
  change. This also covers an ACK on the grant's own first cycle, which the
  old `if/elif` chain silently dropped.
- The owner's ACK bit is a sampled level, paired with the current grant and
  handed to the compliance model every cycle it is high. Stray bits from
  clients that do not hold the grant stay edge-detected, so a held stray bit
  is reported once, not once per cycle.
- `grant_continuation` is no longer emitted. A grant that persists after its
  ACK is reported as the new grant it is; a grant waiting for its ACK reports
  nothing, as before. In ACK mode `grants_per_client` therefore now counts
  grants, not cycles -- the WRR testbench's note that it "over-counts there"
  no longer applies.

### 3. The verdict under-counted past 200 warnings, and could drop errors -- fixed 2026-10-04

Found by the assertion added for defect 2. `_record_warning` kept at most
`max_warnings = 200` entries in `protocol_warnings` and **halved the list** on
overflow; `get_warning_summary` counted from that list. At 16 clients a
testbench that injected 789 stray ACKs on purpose got a verdict of 183. The
list is shared with error-severity entries, so the halving discards errors
too: unit-tested, two `round_robin_violation` errors followed by 800 warnings
produced `total_errors == 0` -- and `total_errors == 0` is the gate every
arbiter testbench asserts on. In both modes.

**The fix:** running totals by type and severity (`_warning_totals`,
`_error_totals`) that are never truncated; the verdict is computed from them.
`protocol_warnings` stays a bounded detail list, but overflow now keeps every
error entry and discards only the oldest warnings.

## Measured

Simple ACK arbiter, 4 clients: `unexpected_ack` 176 -> 42, all 42 being stray
ACKs the testbench injects on purpose -- it now asserts the reported count
equals the injected count exactly, at every N from 2 to 16; single-requester
windows land on their targets (1000/500) instead of 5,002; the run takes
6.8 s instead of 26 s. `arbiter_round_robin[4-1]` unchanged at 0 warnings.
`arbiter_round_robin_weighted[4-8-1]` 7/7 scenarios. No-ACK simple arbiter
0 warnings at every N.

## Three traps for whoever touches this next

**The mask state advances during replay, not live.** Grants and ACKs are
queued and `run_compliance_analysis` walks that queue later. Anything changed
from the monitor's sampling loop touches state the replay re-derives and
changes nothing -- the first attempt at the `r_last_valid` fix did exactly
that, ran clean, and had zero effect on the violation.

**The replay cannot see cycles, only grants.** Idle counts must be measured
by the sampling loop and handed over (`idle_before`). Inferring them from
transaction timestamps looks equivalent and is not: that inference produced
40-60 false violations per run.

**Measure a monitor fix on an arbiter that exercises the path, and count
what the verdict should say before trusting it.** The main arbiter's Rule 3
bubble made back-to-back same-client grants impossible, so "both symptoms to
zero" there said nothing about the re-grant path; and a verdict that said 183
where 789 were logged went unnoticed until a testbench knew the right number.
The simulator-free harness in `tests/unit/test_arbiter_monitor_ack_mode.py`
drives the shapes directly: back-to-back re-grant, same-cycle ACK, level-held
ACK, hand-off without `grant_valid` dropping, the Rule 3 bubble, a grant held
without ACK, and a stray ACK.

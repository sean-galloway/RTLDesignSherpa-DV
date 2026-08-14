# Tasks

One place to see what is going on across the package. Each area has its own
directory with an `INDEX.md` and its lifecycle pages:

```
vault/Tasks/<area>/
  INDEX.md    rollup: counts + the active/open shortlist
  active.md   in progress right now
  open.md     accepted, ready to start
  deferred.md accepted, deliberately PARKED - waiting on a named external
              condition (a datasheet, a DUT, a decision), not on effort
  closed.md   done (completed; kept for history, not deleted)
  dropped.md  ended without completing (abandoned / superseded / won't do)
```

`closed` and `dropped` are both terminal but they are not the same thing:
`closed` means the work got done, `dropped` means we decided not to do it.
Keeping them apart is what makes the history honest — a dropped task should
never read as an accomplishment.

`open` and `deferred` are both pending but they are not the same either:
`open` means someone could start it today; `deferred` means starting it today
would be wrong, and its block must NAME the condition that un-defers it, so
the parking is a recorded decision rather than quiet neglect.

## Lifecycle

A task moves `open → active → closed` — or to `dropped` if it ends without
being completed, or `open ↔ deferred` when the blocker is an external
condition rather than effort — by **cutting** its block from one page and
pasting it into the next. Never copy: a task must exist in exactly one state.
Keep the `**Status:**` line current with a date, and for dropped/deferred a
one-line reason (for deferred: the condition that un-defers it).

## Areas

| Area | Status | Covers | Source (pre-migration) |
|---|---|---|---|
| [dfi](dfi/INDEX.md) | **migrated** | DFI BFMs: CA maps, state model, BFM parity | `TODO.md` §"DFI BFM Capability Parity" (D1–D11, folded in 2026-08-13) |

Other component families (axi4, gaxi, apb, axis, …) have no task pages yet;
their outstanding work is tracked as GitHub issues. Create an area directory
when a family accumulates enough in-flight work to need a rollup.

## Reporting status

`vault/Tasks/<area>/INDEX.md` is the human-readable rollup for that area;
this file is the cross-area map. When you start or finish work, update the
area INDEX counts so the one-place view stays true.

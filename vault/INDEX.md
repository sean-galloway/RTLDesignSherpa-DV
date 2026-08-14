---
title: RTLDesignSherpa-DV vault
summary: Work tracking for the CocoTBFramework package. Mirrors the main repo's vault convention.
---

# RTLDesignSherpa-DV vault

Everything this repo knows that is not code or CHANGELOG. Open the directory
as an Obsidian vault; `[[wikilinks]]` resolve across areas because they share
one root.

| Area | Holds | Answers |
|---|---|---|
| **[handbook](handbook/INDEX.md)** | maintainer practice, as atomic wikilinked notes | "how do I change this package?" |
| **[Tasks](Tasks/INDEX.md)** | work items with an open/active/deferred/closed/dropped lifecycle | "what is in flight?" |

This vault is deliberately smaller than the main repo's, and the reason is
worth holding onto. The main repo's `vault/handbook/dv/` already documents how
to *use* these BFMs to verify RTL — regressions, seeds, coverage, TB
structure, randomization — and several of its notes name this package
directly. None of that is restated here.

What is local to this repo is (a) the work, and (b) the practice of
maintaining a *published package*: packaging and the wheel boundary, spec
fidelity for protocol collateral, differential testing against an anchor, and
release hygiene. That has no home in the main repo, which is why the handbook
here exists rather than pointing everything at the other one.

Per-block RTL context lives in the main repo's `vault/repo-wide-projects/`.

## Relationship to GitHub issues

Both are real here, and they are not redundant. This package is published to
PyPI as `cocotb-framework`, so an externally visible change gets a **GitHub
issue** (the public record, referenced from CHANGELOG). The vault is the
**working** record: what is in flight, what is parked and why, and the
reading order for someone picking an area up. A task block should name its
issue when it has one.

## The one rule

All task tracking lives here. Do not add a `TASKS.md` or `*_TODO.md` next to
code. `TODO.md` at the repo root predates this vault and is retained only as
the issue-drafting record for work already shipped in 0.2.0 — its DFI section
was migrated here 2026-08-13.

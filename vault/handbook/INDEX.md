---
title: CocoTBFramework maintainer handbook
summary: How to work ON this package - packaging, spec fidelity, differential testing, tests and release hygiene. Practice for USING the BFMs lives in the main repo's handbook.
---

# Handbook

Atomic notes, one topic each. `[[name]]` links resolve within this vault
(Obsidian-compatible). Indexes are navigation only — content lives in notes.

## The split that keeps this from rotting

There are two handbooks and they answer different questions. Putting a note
in the wrong one is how it stops being found:

| Question | Where |
|---|---|
| "How do I verify RTL with these BFMs?" — regressions, seeds, coverage, TB structure, randomization profiles, register testing | main repo `vault/handbook/dv/` |
| "How do I change this package?" — packaging, spec fidelity, differential testing, release hygiene | **here** |

The main repo's `dv/` area is the *consumer* view and already includes notes
about this package by name — `bfm-usage`, `rds-dv-axes`,
`arbiter-compliance-model` (plain names, not wikilinks: they live in the other
vault and would dangle here). Do not restate any of it. This handbook is the
*maintainer* view, and nothing in it has a home over there.

## Notes

- [[packaging]] — the package is consumed as a built wheel, and data files are
  not code: both facts have bitten a release
- [[spec-fidelity]] — protocol collateral must be grounded in an on-disk
  specification; what to do when the spec genuinely leaves a value undefined
- [[differential-testing]] — when two things encode the same truth table, one
  is the anchor and the other is tested against it
- [[data-driven-devices]] — if it varies per device, it belongs in data, not
  in a new branch
- [[unit-tests]] — the unit/sim split, the environment, and scoping a
  formatter so it does not rewrite the repo
- [[issues-and-changelog]] — what gets a GitHub issue, what gets a vault task,
  what gets a CHANGELOG line, and the case where none of them apply

## House rules for the handbook itself

- One topic per note; link, never duplicate.
- Every note has title/summary frontmatter so indexes can be regenerated.
- A lesson earned by a real failure names the failure — the case study is the
  part a future reader trusts.
- No emojis.

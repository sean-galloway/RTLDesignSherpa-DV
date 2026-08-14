---
title: Issues, tasks, and the CHANGELOG
summary: Four records with different jobs - GitHub issues are the public trail for a published package, the vault is the working state, CHANGELOG is what shipped, and beta harness work uses none of them.
---

# Issues, tasks, and the CHANGELOG

This package is published, so a change here can reach someone who never sees
this repo. That is why the paperwork exists, and it is also why there is more
than one kind.

| Record | Job | Audience |
|---|---|---|
| **GitHub issue** | the public trail for an externally visible change | users, future archaeology |
| **vault task** | what is in flight, what is parked and on what condition | whoever picks the area up |
| **CHANGELOG** | what actually shipped, per release | anyone upgrading |
| **commit message** | why this change, and what it cost to learn | reviewers, `git log` |

They are not redundant. An issue says *this was decided*; a task says *this is
the current state*; the CHANGELOG says *this reached a user*. A task block
should name its issue when it has one.

## File the issue at push time

For a DV-repo fix or feature, file the GitHub issue when you push — not later,
not when asked. The issue number goes in the CHANGELOG entry, and the push
comment on the issue is where the detail lives (what the commit did, what it
did not, what is still open). Do not wait to be prompted.

## The exception: beta harness work

While a harness is in beta — `ddr2-characterization` and its siblings were the
motivating case — **do not** file issues for its churn. Handle it in
conversation. Filing during a period of rapid, expected change produces a
stream of issues that are stale before anyone reads them, which devalues the
issue trail for the changes that matter. Once the harness stabilises, the
normal rule resumes.

## Solo work does not get a PR

Do not open pull requests for solo work in this repo unless asked. Commit,
fast-forward to `main`, push. A PR whose only reviewer is its author records
process, not review.

Push with an explicit refspec — `git push origin HEAD:main` — because a plain
`git push origin main` has silently reported "up to date" while the remote was
behind, when another agent's ref activity was in play. Verify with
`git ls-remote origin main` rather than trusting the push output.

## Working alongside another agent

When two agents share a checkout, the index is shared. Stage by explicit
pathspec, never `git add -A`, and check `git show --name-only` after
committing to confirm nothing of theirs was swept in. If a commit of yours
turns up inside someone else's, compare the content before worrying: identical
content pushed twice is harmless.

Never stage a file you did not change. The main repo carries a large body of
work-in-progress that must not be committed.

## What earns a CHANGELOG line

Anything a user of the wheel could notice: new API, changed behaviour, a bug
fix, or shipped data files. Internal refactors that leave the surface
identical usually do not — but a fix whose *absence* was invisible (the 0.6.1
`package-data` omission in [[packaging]]) absolutely does, because the user
experienced it even though no API changed.

Write the entry so it survives without its diff: state what changed, and where
a decision was involved, why. Note any limit on the claim — see
[[spec-fidelity]] for the rule about not advertising protocol support that has
not been simulation-exercised.

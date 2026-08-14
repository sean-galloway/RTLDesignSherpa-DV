<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. Move a task between pages by cutting its block, do not copy. -->

# dfi — Open (accepted, not started)

---

## DFI-010 — Cut the 0.6.4 release
**Status:** open 2026-08-13 — the only DFI item not parked; it is a
packaging action, not protocol work

`CHANGELOG.md` `[Unreleased]` has accumulated since 0.6.3 (2026-08-09):
the whole CA-map stack (DFI-001…005) plus the HBM4 work (DFI-006).
The main repo consumes this package as a built wheel, so a release is
what actually propagates it beyond the local editable install.

**Note the standing constraint:** do not advertise the LPDDR/multi-version
DFI features in release notes until fresh-design validation lands — the
maps are spec-verified but not simulation-exercised ([[DFI-023]]).

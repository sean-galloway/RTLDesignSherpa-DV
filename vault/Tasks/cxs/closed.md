<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. -->

# cxs — Closed

## CXS-001 — Add the CXS BFM family (Issues A-D, CXS-Lite)
**Status:** closed 2026-10-15

Shipped `src/CocoTBFramework/components/cxs/`: `cxs_config.py` (per-issue
legality, rule numbers shared with RTLDesignSherpa `cxs_pkg::config_error`),
`cxs_cntl.py`, `cxs_check.py`, `cxs_packet.py`, `cxs_components.py`
(Transmitter / Receiver / Monitor), `cxs_factories.py`. Unit tests
`tests/unit/test_cxs_config.py`, `tests/unit/test_cxs_packet.py`; docs
`docs/components/cxs/`.

Verified by the unit suite and in simulation by RTLDesignSherpa
`val/amba/test_cxs_{master,slave}[_cg].py` (FULL 58/58), whose six RTL
mutations the BFMs all detect.

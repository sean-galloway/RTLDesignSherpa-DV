<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. -->

# axi3 — Closed

## AXI3-001 — Add standalone AXI3 BFM family
**Status:** closed 2026-10-10 — issue #87

Shipped a standalone AXI3 protocol family in `src/CocoTBFramework/components/axi3/`:

- `axi3_field_configs.py` — channel field configs with 4-bit LEN, 2-bit LOCK, WID, no QoS/REGION.
- `axi3_packet.py` — `AXI3Packet` with WID support and protocol validation.
- `axi3_interfaces.py` — `AXI3MasterRead`, `AXI3MasterWrite`, `AXI3SlaveRead`, `AXI3SlaveWrite`. The master sets `WID = AWID` and does not interleave; the slave demuxes W beats by WID.
- `axi3_factories.py` and `__init__.py` — factory functions and package exports.
- Added `axi3_*` entries to `protocol_types.py` and `signal_mapping_helper.py`.
- Added unit tests, docs, and updated `components_index.md` / `mkdocs.yml`.

Verified by the unit-test suite.

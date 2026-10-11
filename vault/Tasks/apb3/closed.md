<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. -->

# apb3 — Closed

## APB3-001 — Add APB3 BFM family as APB4 subclass
**Status:** closed 2026-10-10 — issue #87

Shipped the APB3 protocol family in `src/CocoTBFramework/components/apb3/`:

- `apb3_packet.py` — `APB3Packet` with the APB3 signal set (`pwrite`, `paddr`, `pwdata`, `prdata`, `pslverr`); `PSTRB`/`PPROT` kwargs are ignored.
- `apb3_components.py` — `APB3Master`, `APB3Slave`, `APB3Monitor` subclassing the APB4 BFMs. Only `PSLVERR` is optional; `PPROT`/`PSTRB` are not in the APB3 signal set. `APB3Master.write/read` raise if `strb` or `pprot` is supplied.
- `apb3_factories.py` and `__init__.py` — factory functions and package exports.
- Added unit tests, docs, and updated `components_index.md` / `mkdocs.yml`.

Verified by the unit-test suite.

# `_tb_support/` provenance

Snapshot of RDS's `bin/TBClasses/` — the framework-side test infrastructure
that the BFM acceptance tests in `tests/sim/bfm_acceptance/` depend on.

## Source

| Field | Value |
|---|---|
| Source repo | `sean-galloway/RTLDesignSherpa` |
| Source commit | `7aee11af7a8363fbafa75465f7e704f0328debeb` |
| Source date | 2026-06-09 |
| Source path | `bin/TBClasses/` |
| Copied on | 2026-06-09 |

## What's here

- **`shared/tbbase.py`** — the `TBBase` class that all testbench classes
  extend. Provides clock control (`start_clock`, `wait_clocks`), logger
  setup, env-var helpers (`convert_to_int`, `format_dec`).
- **`shared/utilities.py`** — `get_paths`, `get_wave_config`,
  `create_view_cmd`, `get_repo_root`.
- **`shared/filelist_utils.py`** — `get_sources_from_filelist` which
  parses `.f` files and resolves `$REPO_ROOT` references.
- **`gaxi/`** — `GaxiBufferTB`, configs, and field/multi-sig variants
  used by `test_gaxi_buffer_*`.
- **`fifo/`** — same shape as `gaxi/` for FIFO buffer tests.
- **`amba/`** — `APB_SLAVE_RANDOMIZER_CONFIGS`, `AXI_RANDOMIZER_CONFIGS`,
  the named randomizer presets used by `test_apb_master.py` and friends.

`tests/sim/conftest.py` registers this directory as the `TBClasses` package
so tests can `from TBClasses.shared.tbbase import TBBase` and have it
resolve here rather than to a sibling RDS checkout.

## Updating

When you want to track a newer RDS commit:

```bash
RDS=/path/to/RTLDesignSherpa
for sub in shared gaxi fifo amba; do
  cp "$RDS/bin/TBClasses/$sub"/*.py tests/sim/_tb_support/$sub/
done
# Update the commit SHA above and commit.
```

If RDS adds new `TBClasses/` subpackages you want to use (e.g. `axi4/`),
add them to the copy and create them under `_tb_support/`.

## Why a snapshot instead of a submodule

The snapshot makes the DV repo's BFM acceptance suite self-contained —
`pytest tests/sim/bfm_acceptance/` works after a clone without needing
the user to set up an RDS submodule. The RTL itself still needs an RDS
checkout (via `RDS_RTL_PATH` or the `_rds/` submodule) because the RTL
volume would be impractical to snapshot, but the Python TB infrastructure
is small enough (a few thousand lines) to vendor.

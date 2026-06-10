"""Tier 2 sim test configuration.

Sets up the import path so existing RDS-style tests (which import
``TBClasses.*``) work unmodified, sourcing those modules from this
DV repo's ``TBClasses/`` snapshot rather than from a sibling RDS
checkout.

For the ``$REPO_ROOT`` substitution used by ``get_paths`` and the
filelist parser to resolve RTL paths, we look first at the
``RDS_RTL_PATH`` environment variable (developer workflow — points
at a sibling RDS checkout); if unset, we fall back to ``tests/sim/_rds/``
which will eventually be a git submodule pinned to a known RDS commit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Make tests/sim/TBClasses/ importable as `TBClasses.*`
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent

# `tests/sim/TBClasses/` is a snapshot of RDS's `bin/TBClasses/`. Putting
# its parent (tests/sim/) on sys.path makes the package importable as
# `TBClasses.*` — matching what the existing RDS tests in
# `bfm_acceptance/` already import.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ---------------------------------------------------------------------------
# RDS root resolution for $REPO_ROOT substitution in filelists
# ---------------------------------------------------------------------------


def _resolve_rds_root() -> Path | None:
    """Find the RDS repo root for filelist `$REPO_ROOT` substitution."""
    if env := os.environ.get("RDS_RTL_PATH"):
        path = Path(env).expanduser().resolve()
        if (path / "rtl" / "amba").is_dir():
            return path
        raise RuntimeError(
            f"RDS_RTL_PATH={env} does not look like an RDS checkout "
            f"(expected to find rtl/amba/ under it)"
        )

    submodule = _HERE / "_rds"
    if (submodule / "rtl" / "amba").is_dir():
        return submodule.resolve()

    return None


@pytest.fixture(scope="session")
def rds_root() -> Path:
    """Path to the RDS repo root (for filelist resolution)."""
    root = _resolve_rds_root()
    if root is None:
        pytest.skip(
            "RDS RTL not available. Either set RDS_RTL_PATH=/path/to/RTLDesignSherpa "
            "or initialize the tests/sim/_rds/ git submodule."
        )
    return root


@pytest.fixture(autouse=True)
def _set_repo_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set ``$REPO_ROOT`` in the environment so filelist substitution works.

    `get_sources_from_filelist` uses ``os.environ['REPO_ROOT']`` to resolve
    paths like ``$REPO_ROOT/rtl/amba/...`` in `.f` filelists.
    """
    root = _resolve_rds_root()
    if root is not None:
        monkeypatch.setenv("REPO_ROOT", str(root))


# ---------------------------------------------------------------------------
# Skip Tier 2 tests if prerequisites aren't available
# ---------------------------------------------------------------------------


def _has_cocotb_test() -> bool:
    """Check if the cocotb-test package is importable."""
    try:
        import cocotb_test.simulator  # noqa: F401
    except ImportError:
        return False
    return True


def _has_simulator() -> bool:
    """Check if a Verilog simulator is on PATH."""
    import shutil
    return any(shutil.which(s) for s in ("verilator", "iverilog", "vsim", "xcelium"))


_TIER2_PREREQ_MESSAGE: str | None = None


def pytest_ignore_collect(collection_path, config):
    """Skip collecting Tier 2 test modules if prerequisites are missing.

    Without this, pytest tries to import each test module — and the
    ``from cocotb_test.simulator import run`` at the top raises an
    ImportError that fails collection (rather than just skipping). By
    short-circuiting at collection we let unit tests pass on a machine
    that doesn't have cocotb-test or a Verilog simulator installed.
    """
    global _TIER2_PREREQ_MESSAGE
    path_str = str(collection_path)
    # Tier 2 test directories (need cocotb-test + a simulator)
    tier2_dirs = ("tests/sim/bfm_acceptance", "tests/sim/bridges")
    if not any(d in path_str for d in tier2_dirs):
        return None
    if not _has_cocotb_test():
        _TIER2_PREREQ_MESSAGE = (
            "Tier 2 BFM acceptance tests skipped: cocotb-test not installed "
            "(pip install cocotb-test)"
        )
        return True
    if not _has_simulator():
        _TIER2_PREREQ_MESSAGE = (
            "Tier 2 BFM acceptance tests skipped: no Verilog simulator on PATH "
            "(install verilator/iverilog/vsim/xcelium)"
        )
        return True
    return None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print a one-line note when Tier 2 was skipped, so the reason is visible."""
    if _TIER2_PREREQ_MESSAGE:
        terminalreporter.write_line(_TIER2_PREREQ_MESSAGE)

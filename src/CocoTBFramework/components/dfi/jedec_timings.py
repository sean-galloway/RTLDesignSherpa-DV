# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""JEDEC DRAM timing table loader (issue #16).

The :class:`JedecTimings` dataclass holds the cycle counts the
:class:`~.dram_state.DramStateModel` needs to check command sequences
against. CSV format is documented in ``jedec/README.md``.

Pre-alpha note: the CSV schema is provisional. If a parameter the
checker doesn't know about appears, it's preserved in ``extras`` rather
than rejected — so the loader stays forward-compatible with new
timings the user dumps from their own tools.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union

_REQUIRED_PARAMS = (
    "tCK",
    "tRCD", "tRP", "tRAS_min", "tRC",
    "tWR", "tWTR", "tRTP", "tRRD",
    "tFAW", "tREFI", "tRFC",
    "CL", "CWL", "BL",
)


@dataclass(frozen=True)
class JedecTimings:
    """JEDEC timing parameters in DFI clock cycles.

    All ``t*_cycles`` values are converted from the CSV's ``ns`` entries
    using ``tCK_ns`` (rounded up). ``CL``, ``CWL``, ``BL`` are already
    in cycles / beats and are stored as-is.

    ``extras`` keeps any parameter the loader didn't recognize so the
    checker can reach into them without changes to this schema.
    """

    tCK_ns: float
    tRCD_cycles: int
    tRP_cycles: int
    tRAS_min_cycles: int
    tRC_cycles: int
    tWR_cycles: int
    tWTR_cycles: int
    tRTP_cycles: int
    tRRD_cycles: int
    tFAW_cycles: int
    tREFI_cycles: int
    tRFC_cycles: int
    CL: int
    CWL: int
    BL: int
    extras: Dict[str, float] = field(default_factory=dict)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def ns_to_cycles(ns: float, tCK_ns: float) -> int:
    """Convert ``ns`` to cycles at ``tCK_ns`` clock period (ceiling).

    Spec convention: round up so the BFM enforces at least the timing
    the spec calls for. ``ceil(13.75 / 1.25) = 11`` for DDR3-1600 tRCD.
    """
    if tCK_ns <= 0:
        raise ValueError(f"tCK_ns must be positive, got {tCK_ns}")
    return math.ceil(ns / tCK_ns)


def _parse_value(value_str: str, unit: str, tCK_ns: Optional[float]) -> Union[int, float]:
    """Convert one CSV value to its canonical representation."""
    unit = unit.strip().lower()
    raw = float(value_str.strip())
    if unit == "ns":
        if tCK_ns is None:
            raise ValueError("tCK must be the first parameter so ns→cycles "
                             "conversion has a clock period")
        return ns_to_cycles(raw, tCK_ns)
    if unit == "ck":
        return int(raw)
    if unit == "beats":
        return int(raw)
    raise ValueError(f"Unknown unit {unit!r} — expected ns | CK | beats")


# ----------------------------------------------------------------------
# Public loader
# ----------------------------------------------------------------------


def load_timings(csv_path: Union[str, Path]) -> JedecTimings:
    """Parse a JEDEC CSV file and return a :class:`JedecTimings`.

    See ``jedec/README.md`` for the format.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"JEDEC CSV not found: {csv_path}")

    parsed: Dict[str, Union[int, float]] = {}
    tCK_ns: Optional[float] = None

    with path.open(newline="", encoding="utf-8") as f:
        # Strip comments before handing to csv.reader; the csv module
        # doesn't know about '#' comments.
        cleaned = []
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            cleaned.append(line)
        reader = csv.reader(cleaned)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{csv_path}: empty CSV")
        header = [c.strip().lower() for c in header]
        expected_header = ["parameter", "unit", "value", "description"]
        if header != expected_header:
            raise ValueError(
                f"{csv_path}: bad header {header!r}; "
                f"expected {expected_header!r}"
            )
        for row in reader:
            if len(row) < 3:
                raise ValueError(f"{csv_path}: malformed row {row!r}")
            name = row[0].strip()
            unit = row[1].strip()
            value = row[2].strip()
            if name == "tCK":
                # Special case: tCK stores the ns period directly.
                tCK_ns = float(value)
                parsed["tCK_ns"] = tCK_ns
                continue
            parsed[name] = _parse_value(value, unit, tCK_ns)

    if "tCK_ns" not in parsed:
        raise ValueError(
            f"{csv_path}: tCK parameter missing — required as first row "
            "(needed to convert ns values to cycles)"
        )

    # Pull required params; anything extra goes into `extras`.
    required = {p for p in _REQUIRED_PARAMS if p != "tCK"}
    missing = required - set(parsed.keys())
    if missing:
        raise ValueError(
            f"{csv_path}: missing required parameter(s) "
            f"{sorted(missing)}"
        )

    extras = {
        k: float(v) for k, v in parsed.items()
        if k not in _REQUIRED_PARAMS and k != "tCK_ns"
    }

    return JedecTimings(
        tCK_ns=parsed["tCK_ns"],
        tRCD_cycles=int(parsed["tRCD"]),
        tRP_cycles=int(parsed["tRP"]),
        tRAS_min_cycles=int(parsed["tRAS_min"]),
        tRC_cycles=int(parsed["tRC"]),
        tWR_cycles=int(parsed["tWR"]),
        tWTR_cycles=int(parsed["tWTR"]),
        tRTP_cycles=int(parsed["tRTP"]),
        tRRD_cycles=int(parsed["tRRD"]),
        tFAW_cycles=int(parsed["tFAW"]),
        tREFI_cycles=int(parsed["tREFI"]),
        tRFC_cycles=int(parsed["tRFC"]),
        CL=int(parsed["CL"]),
        CWL=int(parsed["CWL"]),
        BL=int(parsed["BL"]),
        extras=extras,
    )


def _jedec_dir() -> Path:
    return Path(__file__).parent / "jedec"


def available_timings() -> list:
    """Names accepted by :func:`builtin_timings`, sorted.

    Only devices whose timings are fixed by a public JEDEC speed bin are
    vendored. Devices whose AC timings are vendor-defined (HBM stacks,
    for instance) are deliberately absent — see
    :func:`timings_from_params` for those.
    """
    return sorted(p.stem for p in _jedec_dir().glob("*.csv"))


def builtin_timings(name: str) -> JedecTimings:
    """Convenience loader for the CSVs vendored in this package.

    Usage:
        timings = builtin_timings("ddr3-1600")
    """
    path = _jedec_dir() / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"No built-in timing profile {name!r}. Available: "
            f"{', '.join(available_timings())}.\n"
            "Profiles are vendored only where a public JEDEC speed bin "
            "fixes the numbers. For a device whose AC timings come from a "
            "vendor datasheet, build them from your own values with "
            "timings_from_params(...) or load_timings('your.csv') and pass "
            "the result as the slave's timings= argument."
        )
    return load_timings(path)


def timings_from_params(**params) -> JedecTimings:
    """Build :class:`JedecTimings` from values in code, no CSV needed.

    For parts whose AC timings this package cannot ship — anything
    vendor-defined rather than fixed by a public JEDEC speed bin — this
    is how a consumer supplies their own. It applies exactly the same
    conversion the CSV loader does, so a profile built here and one
    loaded from a file are indistinguishable downstream.

    Each timing is given with an explicit unit suffix, in whichever form
    the datasheet quotes it:

        ``tRCD_ns=13.75``   nanoseconds, converted with ceiling rounding
        ``tRCD_ck=11``      already in clock cycles, taken as-is

    ``tCK_ns`` is always required, as are ``CL``, ``CWL`` and ``BL``
    (unitless). Parameters outside the required set are kept in
    ``extras`` under their bare name, matching the loader.

        >>> t = timings_from_params(
        ...     tCK_ns=0.3125, tRCD_ns=18.0, tRP_ns=18.0,
        ...     tRAS_min_ns=32.0, tRC_ns=50.0, tWR_ns=30.0,
        ...     tWTR_ns=10.0, tRTP_ns=7.5, tRRD_ns=8.0, tFAW_ns=40.0,
        ...     tREFI_ns=3900.0, tRFC_ns=295.0, CL=40, CWL=38, BL=16)
        >>> t.tRCD_cycles
        58

    Raises ValueError listing exactly what is missing or unrecognized,
    so a caller working from a datasheet is told what to look up next.
    """
    unitless = {"CL", "CWL", "BL"}

    if "tCK_ns" not in params:
        raise ValueError(
            "tCK_ns is required — every ns value is converted to cycles "
            "with it"
        )
    tCK_ns = float(params.pop("tCK_ns"))
    if tCK_ns <= 0:
        raise ValueError(f"tCK_ns must be positive, got {tCK_ns}")

    parsed: Dict[str, Union[int, float]] = {}
    bad_suffix = []
    for key, value in params.items():
        if key in unitless:
            parsed[key] = int(value)
        elif key.endswith("_ns"):
            parsed[key[:-3]] = ns_to_cycles(float(value), tCK_ns)
        elif key.endswith("_ck"):
            parsed[key[:-3]] = int(value)
        else:
            bad_suffix.append(key)

    if bad_suffix:
        raise ValueError(
            f"Parameter(s) {sorted(bad_suffix)} need an explicit unit "
            "suffix: '_ns' for nanoseconds or '_ck' for clock cycles "
            f"(the unitless ones are {sorted(unitless)})"
        )

    required = {p for p in _REQUIRED_PARAMS if p != "tCK"}
    missing = required - set(parsed)
    if missing:
        raise ValueError(
            f"missing required parameter(s) {sorted(missing)} — supply "
            "each as <name>_ns or <name>_ck"
        )

    extras = {k: float(v) for k, v in parsed.items()
              if k not in _REQUIRED_PARAMS}

    return JedecTimings(
        tCK_ns=tCK_ns,
        tRCD_cycles=int(parsed["tRCD"]),
        tRP_cycles=int(parsed["tRP"]),
        tRAS_min_cycles=int(parsed["tRAS_min"]),
        tRC_cycles=int(parsed["tRC"]),
        tWR_cycles=int(parsed["tWR"]),
        tWTR_cycles=int(parsed["tWTR"]),
        tRTP_cycles=int(parsed["tRTP"]),
        tRRD_cycles=int(parsed["tRRD"]),
        tFAW_cycles=int(parsed["tFAW"]),
        tREFI_cycles=int(parsed["tREFI"]),
        tRFC_cycles=int(parsed["tRFC"]),
        CL=int(parsed["CL"]),
        CWL=int(parsed["CWL"]),
        BL=int(parsed["BL"]),
        extras=extras,
    )


_TEMPLATE_DESCRIPTIONS = {
    "tCK": "Clock period",
    "tRCD": "Activate to Read/Write, same bank",
    "tRP": "Precharge command period",
    "tRAS_min": "Activate to Precharge, minimum",
    "tRC": "Activate to Activate, same bank",
    "tWR": "Write recovery",
    "tWTR": "Write to Read turnaround",
    "tRTP": "Read to Precharge",
    "tRRD": "Activate to Activate, different bank",
    "tFAW": "Four activate window",
    "tREFI": "Average refresh interval",
    "tRFC": "Refresh cycle time",
    "CL": "CAS latency",
    "CWL": "CAS write latency",
    "BL": "Burst length",
}


def write_timings_template(csv_path: Union[str, Path],
                           device: str = "<device>") -> Path:
    """Write a blank CSV with every parameter the loader requires.

    The companion to :func:`timings_from_params` for people who would
    rather keep timings in a file next to the testbench than in code.
    Values are left empty on purpose: filling them in is a datasheet
    lookup, and a template carrying plausible-looking defaults would be
    indistinguishable from a real profile once someone forgot to edit it.
    """
    path = Path(csv_path)
    unit = {"CL": "CK", "CWL": "CK", "BL": "beats"}
    lines = [
        f"# {device} timing profile — fill in from the datasheet.",
        "# Units: ns (converted to cycles, rounded up) | CK | beats.",
        "# tCK must stay first; it sets the ns->cycle conversion.",
        "# Extra rows beyond these are preserved in JedecTimings.extras.",
        "",
        "parameter, unit, value, description",
    ]
    lines += [f"{p}, {unit.get(p, 'ns')}, , {_TEMPLATE_DESCRIPTIONS[p]}"
              for p in _REQUIRED_PARAMS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

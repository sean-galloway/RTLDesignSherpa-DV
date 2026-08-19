"""Consumer-supplied timing profiles.

Only devices whose AC timings a public JEDEC speed bin pins down are
vendored as CSVs. HBM stacks (JESD270-4A leaves the AC table
vendor-defined) and any part we have no spec for cannot be shipped, and
inventing numbers for them would be worse than shipping nothing. But
`DFIBase` takes `timings` as a mandatory argument, so without a way to
supply your own, an unshipped device is simply unusable — you cannot
construct the slave at all, however well its CA bus decodes.

These cover the two supported ways to close that gap
(`timings_from_params` in code, `write_timings_template` on disk) and,
most importantly, that a profile built by hand is indistinguishable
downstream from one loaded from a vendored CSV.
"""

import csv
from pathlib import Path

import pytest

from CocoTBFramework.components.dfi.jedec_timings import (
    JedecTimings,
    available_timings,
    builtin_timings,
    load_timings,
    timings_from_params,
    write_timings_template,
)

# ---------------------------------------------------------------- discovery


def test_available_timings_lists_the_vendored_profiles():
    names = available_timings()
    assert "ddr3-1600" in names
    assert names == sorted(names)
    # Nothing vendor-defined should have crept in.
    assert not [n for n in names if n.startswith("hbm")]


def test_unknown_profile_names_what_exists_and_the_way_out():
    """The error is the only documentation a caller hits at 2am."""
    with pytest.raises(FileNotFoundError) as exc:
        builtin_timings("hbm4")
    msg = str(exc.value)
    assert "ddr3-1600" in msg, "should list what IS available"
    assert "timings_from_params" in msg, "should name the way out"


# ------------------------------------------------------- in-code construction


def test_matches_the_csv_loader_exactly():
    """A hand-built profile must be indistinguishable from a loaded one.

    Rebuilds a vendored profile from its own CSV rows through the
    public API; any divergence in rounding or unit handling shows up
    as a field mismatch.
    """
    name = "ddr3-1600"
    from_csv = builtin_timings(name)

    path = Path(__file__).resolve().parents[2] / (
        "src/CocoTBFramework/components/dfi/jedec") / f"{name}.csv"
    rows = [r for r in csv.reader(
        line for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#"))][1:]

    kwargs = {}
    for name_, unit, value, *_ in rows:
        name_, unit, value = name_.strip(), unit.strip().lower(), value.strip()
        if name_ == "tCK":
            kwargs["tCK_ns"] = float(value)
        elif unit == "ns":
            kwargs[f"{name_}_ns"] = float(value)
        elif unit == "ck":
            kwargs[f"{name_}_ck"] = int(float(value))
        else:                                   # beats -> unitless BL
            kwargs[name_] = int(float(value))

    assert timings_from_params(**kwargs) == from_csv


def test_ns_values_round_up_like_the_spec_requires():
    """Rounding down would let the BFM accept illegal command spacing."""
    t = timings_from_params(**_minimal(tCK_ns=1.25, tRCD_ns=13.75))
    assert t.tRCD_cycles == 11                  # 13.75 / 1.25 exactly
    t = timings_from_params(**_minimal(tCK_ns=1.25, tRCD_ns=13.80))
    assert t.tRCD_cycles == 12                  # 11.04 -> up, never down


def test_cycle_values_pass_through_untouched():
    t = timings_from_params(**_minimal(tCK_ns=1.25, tRCD_ck=9))
    assert t.tRCD_cycles == 9


def test_unrecognized_parameters_land_in_extras():
    t = timings_from_params(**_minimal(tCK_ns=1.25, tCCD_L_ck=8))
    assert t.extras["tCCD_L"] == 8


def test_missing_parameters_are_named():
    kwargs = _minimal(tCK_ns=1.25)
    kwargs.pop("tRFC_ns")
    kwargs.pop("CWL")
    with pytest.raises(ValueError) as exc:
        timings_from_params(**kwargs)
    assert "tRFC" in str(exc.value) and "CWL" in str(exc.value)


def test_a_unit_suffix_is_mandatory():
    """`tRCD=13.75` is ambiguous — ns and cycles differ by ~10x, and
    guessing wrong silently mis-times every command."""
    kwargs = _minimal(tCK_ns=1.25)
    kwargs["tRCD"] = kwargs.pop("tRCD_ns")
    with pytest.raises(ValueError, match="unit suffix"):
        timings_from_params(**kwargs)


def test_tck_is_required():
    kwargs = _minimal(tCK_ns=1.25)
    kwargs.pop("tCK_ns")
    with pytest.raises(ValueError, match="tCK_ns"):
        timings_from_params(**kwargs)


@pytest.mark.parametrize("bad", [0, -1.25])
def test_nonpositive_clock_period_rejected(bad):
    with pytest.raises(ValueError):
        timings_from_params(**_minimal(tCK_ns=bad))


# ------------------------------------------------------------------ template


def test_template_round_trips_once_filled_in(tmp_path):
    """The template must be loadable after a pure fill-in-values edit."""
    path = write_timings_template(tmp_path / "part.csv", device="MY-PART")
    text = path.read_text()
    assert "MY-PART" in text

    filled, values = [], {
        "tCK": "1.25", "tRCD": "13.75", "tRP": "13.75", "tRAS_min": "35.0",
        "tRC": "48.75", "tWR": "15.0", "tWTR": "7.5", "tRTP": "7.5",
        "tRRD": "6.0", "tFAW": "30.0", "tREFI": "7800", "tRFC": "260",
        "CL": "11", "CWL": "8", "BL": "8",
    }
    for line in text.splitlines():
        head = line.split(",")[0].strip()
        if head in values and not line.startswith("#"):
            parts = line.split(",")
            parts[2] = f" {values[head]}"
            line = ",".join(parts)
        filled.append(line)
    path.write_text("\n".join(filled) + "\n")

    t = load_timings(path)
    assert isinstance(t, JedecTimings)
    assert t.tRCD_cycles == 11 and t.CL == 11


def test_template_ships_no_default_values(tmp_path):
    """A template with plausible numbers in it is a profile nobody
    remembers to edit; every value column must be empty."""
    path = write_timings_template(tmp_path / "part.csv")
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.split(",")[0].strip() == "parameter":
            continue
        assert line.split(",")[2].strip() == "", f"template pre-filled: {line}"


def test_unfilled_template_is_rejected_not_silently_zeroed(tmp_path):
    path = write_timings_template(tmp_path / "part.csv")
    with pytest.raises(ValueError):
        load_timings(path)


def _minimal(**overrides):
    """A complete-but-arbitrary parameter set, so each test can vary one
    thing without restating fifteen values."""
    kwargs = {
        "tCK_ns": 1.25, "tRCD_ns": 13.75, "tRP_ns": 13.75,
        "tRAS_min_ns": 35.0, "tRC_ns": 48.75, "tWR_ns": 15.0,
        "tWTR_ns": 7.5, "tRTP_ns": 7.5, "tRRD_ns": 6.0, "tFAW_ns": 30.0,
        "tREFI_ns": 7800.0, "tRFC_ns": 260.0, "CL": 11, "CWL": 8, "BL": 8,
    }
    for key in list(overrides):
        base = key.rsplit("_", 1)[0]
        kwargs.pop(f"{base}_ns", None)
        kwargs.pop(f"{base}_ck", None)
    kwargs.update(overrides)
    return kwargs

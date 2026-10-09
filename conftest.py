"""Repo-root conftest for RTLDesignSherpa-DV.

WHY THIS EXISTS
---------------
cocotb 1.x matched the ``TESTCASE`` env value against test NAMES exactly.
cocotb 2.x reads ``COCOTB_TEST_FILTER`` and matches it with ``re.search``
over ``<module>.<test>`` fullnames. cocotb-test 0.3.0 (latest as of
2026-10-09; no fix released) passes its ``testcase=`` kwarg to
``COCOTB_TEST_FILTER`` UNANCHORED, so ``testcase='foo'`` also selects
``foo_bar`` -- every multi-test module runs ALL its tests in EVERY build.
Observed in the RTLDesignSherpa repo (tooling BUG-015) on
``val/amba/test_axi_monitor_soak.py``, where the pktgen build then failed
on the monlite-only pin.

This conftest anchors every ``testcase=`` as ``\\b<name>$`` before
cocotb-test hands it to the simulator, restoring 1.x exact-name semantics
for every call site in this repo at once. No-op when cocotb-test is not
importable; idempotent. Placed at the repo root so ONE file covers
``tests/`` and any other invocation, per the same rootdir reasoning as
the RTLDesignSherpa seed-pinning conftest.

DELETE THIS when cocotb-test releases a fix that anchors the filter
itself -- a double anchor is harmless regex, but the patch should not
outlive its reason.
"""

import inspect
import re


def _patch_cocotb_testcase_anchor():
    global _TESTCASE_ANCHOR_ACTIVE
    try:
        import cocotb_test.simulator as cts
    except Exception:
        return

    orig = cts.Simulator.__init__
    try:
        tc_pos = list(inspect.signature(orig).parameters).index("testcase") - 1
    except ValueError:
        tc_pos = None

    def anchored(tc: str) -> str:
        return r"\b" + re.escape(tc) + "$"

    def patched(self, *args, **kwargs):
        tc = kwargs.get("testcase")
        if tc is None and tc_pos is not None and len(args) > tc_pos:
            tc = args[tc_pos]
        if isinstance(tc, str):
            if "testcase" in kwargs:
                kwargs["testcase"] = anchored(tc)
            elif tc_pos is not None and len(args) > tc_pos:
                args = args[:tc_pos] + (anchored(tc),) + args[tc_pos + 1:]
        return orig(self, *args, **kwargs)

    cts.Simulator.__init__ = patched
    _TESTCASE_ANCHOR_ACTIVE = True


_TESTCASE_ANCHOR_ACTIVE = False
_patch_cocotb_testcase_anchor()


def pytest_report_header(config):
    if _TESTCASE_ANCHOR_ACTIVE:
        return ("rds-dv: cocotb-test testcase= anchored to exact-name "
                "selection (RDS BUG-015; remove when cocotb-test fixes it)")

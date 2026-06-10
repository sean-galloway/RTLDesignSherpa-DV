"""Shared fixtures and mocks for the behavior-class unit tests.

Behavior methods that have been implemented (not just stubs) sample
cocotb signal handles. The mocks here stand in for those at Tier 1.
"""

from __future__ import annotations


class MockVal:
    """Minimal stand-in for cocotb's BinaryValue."""

    def __init__(self, integer: int = 0):
        self.integer = integer
        self.is_resolvable = True


class MockSig:
    """Minimal stand-in for a cocotb signal handle."""

    def __init__(self, value: int = 0):
        self.value = MockVal(value)


class MockBus:
    """Minimal stand-in for the cocotb bus bundle.

    Pass any signal value as a kwarg; defaults to 0. Used by behavior
    method tests that sample wires (e.g., error_event).
    """

    def __init__(self, **signals):
        for name, value in signals.items():
            setattr(self, name, MockSig(value))

    def __getattr__(self, name: str) -> MockSig:
        # Any signal not explicitly set defaults to 0. Lets tests pass
        # only the signals their behavior method actually reads.
        sig = MockSig(0)
        setattr(self, name, sig)
        return sig

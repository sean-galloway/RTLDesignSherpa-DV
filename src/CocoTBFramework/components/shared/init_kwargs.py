# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa-DV
#
# Module: init_kwargs
# Purpose: Helpers for the cocotb-parent init dance in BFM subclasses
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway

"""Helpers for the cocotb-parent init dance in BFM subclasses.

The framework's BFM classes inherit from ``cocotb_bus.drivers.BusDriver`` or
``cocotb_bus.monitors.BusMonitor`` and accept a number of framework-specific
kwargs (``memory_model``, ``randomizer``, ``signal_map``, ``super_debug``, ...)
that must NOT be forwarded to the cocotb parent's ``__init__`` — cocotb-bus
would reject them as unknown.

Historically each BFM subclass open-coded the strip:

    custom_params = ['bus_name', 'pkt_prefix', 'memory_model', 'randomizer',
                     'signal_map', 'super_debug', 'pipeline_debug']
    for param in custom_params:
        kwargs.pop(param, None)
    BusDriver.__init__(self, dut, '', clock, **kwargs)

This module centralizes the strip so adding a new framework kwarg only
requires updating ``FRAMEWORK_KWARGS`` once. See issue #10.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, MutableMapping

# Canonical set of kwargs that framework BFM subclasses consume internally but
# must strip before forwarding the remainder to a cocotb-bus parent. Add new
# framework-only kwargs here when introducing them.
FRAMEWORK_KWARGS: tuple[str, ...] = (
    "bus_name",
    "pkt_prefix",
    "memory_model",
    "randomizer",
    "signal_map",
    "super_debug",
    "pipeline_debug",
)


def strip_framework_kwargs(
    kwargs: MutableMapping[str, Any],
    *,
    extra: Iterable[str] = (),
) -> None:
    """Remove framework-only kwargs in-place from ``kwargs``.

    Call this just before forwarding ``**kwargs`` to a cocotb-bus
    ``__init__`` to prevent ``TypeError: unexpected keyword argument`` from
    cocotb-bus, which doesn't know about our framework kwargs.

    Args:
        kwargs: The ``**kwargs`` dict from the subclass ``__init__``.
        extra: Additional names to strip beyond :data:`FRAMEWORK_KWARGS`
            (e.g. ``"prefix"`` when the caller is replacing the prefix with
            an empty string).
    """
    for name in FRAMEWORK_KWARGS:
        kwargs.pop(name, None)
    for name in extra:
        kwargs.pop(name, None)


def pop_framework_kwargs(
    kwargs: MutableMapping[str, Any],
    *,
    names: Iterable[str] = FRAMEWORK_KWARGS,
) -> Dict[str, Any]:
    """Pop and return framework kwargs.

    Use when you need the *values* (for example, to forward
    ``memory_model`` and ``randomizer`` to a non-cocotb base class) in
    addition to stripping them from the kwargs that will be forwarded to
    the cocotb parent.
    """
    return {name: kwargs.pop(name, None) for name in names}

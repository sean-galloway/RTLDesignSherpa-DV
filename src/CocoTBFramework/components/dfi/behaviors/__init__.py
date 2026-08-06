# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Per-version behavior classes for the DFI BFM.

See ``docs/internal/dfi-semantic-shifts.md`` for the design rationale.
The public surface is:

  - :class:`DFIv2_1Behavior` (base)
  - per-version subclasses (v3.1, v4.0, v5.2, v6.0)
  - Event types (CRCEvent, UpdateEvent, TakeoverEvent, …)
  - :exc:`NotSupportedInThisVersionError` /
    :exc:`RemovedInThisVersionError`
  - :data:`VERSION_BEHAVIOR` registry
"""

from .base import DFIv2_1Behavior
from .events import (
    CAParityEvent,
    CRCEvent,
    CRCKind,
    DisconnectEvent,
    DisconnectPhase,
    ErrorEvent,
    ErrorKind,
    FreqChangeEvent,
    FreqChangeProtocol,
    LowPowerEvent,
    TakeoverEvent,
    TrainingEvent,
    TrainingPhase,
    UpdateEvent,
    UpdateState,
)
from .exceptions import NotSupportedInThisVersionError, RemovedInThisVersionError
from .registry import VERSION_BEHAVIOR, behavior_for
from .v3_1 import DFIv3_1Behavior
from .v4_0 import DFIv4_0Behavior
from .v5_2 import DFIv5_2Behavior
from .v6_0 import DFIv6_0Behavior

__all__ = [
    "DFIv2_1Behavior",
    "DFIv3_1Behavior",
    "DFIv4_0Behavior",
    "DFIv5_2Behavior",
    "DFIv6_0Behavior",
    "VERSION_BEHAVIOR",
    "behavior_for",
    "NotSupportedInThisVersionError",
    "RemovedInThisVersionError",
    # Events
    "CRCEvent",
    "CRCKind",
    "UpdateEvent",
    "UpdateState",
    "TakeoverEvent",
    "DisconnectEvent",
    "DisconnectPhase",
    "FreqChangeEvent",
    "FreqChangeProtocol",
    "LowPowerEvent",
    "TrainingEvent",
    "TrainingPhase",
    "ErrorEvent",
    "ErrorKind",
    "CAParityEvent",
]

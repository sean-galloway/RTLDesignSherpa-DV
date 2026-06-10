# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Per-version behavior classes for the DFI BFM.

See ``docs/internal/dfi-semantic-shifts.md`` for the design rationale.
The public surface is:

  - :class:`DFIv2_1Behavior` (base)
  - per-version subclasses
  - Event types (CRCEvent, UpdateEvent, TakeoverEvent, …)
  - :exc:`NotSupportedInThisVersionError`
  - :data:`VERSION_BEHAVIOR` registry (lands with the wire-up commit)
"""

from .base import DFIv2_1Behavior
from .v3_1 import DFIv3_1Behavior
from .v4_0 import DFIv4_0Behavior
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
    TakeoverEvent,
    TrainingEvent,
    TrainingPhase,
    UpdateEvent,
    UpdateState,
)
from .exceptions import NotSupportedInThisVersionError

__all__ = [
    "DFIv2_1Behavior",
    "DFIv3_1Behavior",
    "DFIv4_0Behavior",
    "NotSupportedInThisVersionError",
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
    "TrainingEvent",
    "TrainingPhase",
    "ErrorEvent",
    "ErrorKind",
    "CAParityEvent",
]

# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Version → behavior class registry.

This is the **only** place in the codebase that maps a DFI version
enum value to its concrete behavior class. Any other code that needs
to dispatch on version should go through :func:`behavior_for` rather
than testing ``self.dfi_version == DFIVersion.X``. Adding a new DFI
revision is one row in :data:`VERSION_BEHAVIOR`.

The mapping deliberately collapses versions that share semantics:

  - V5_0 / V5_1 / V5_2 → DFIv4_0Behavior
    (v5.0 is corrections-only, v5.1 is signal additions handled by
    the envelope, v5.2 is the PHY-Master rename which has no
    behavior implication. See the catalog's PHY Master/Managed
    open question.)
"""

from __future__ import annotations

from typing import Dict, Type

from ..dfi_signals import DFIVersion
from .base import DFIv2_1Behavior
from .v3_1 import DFIv3_1Behavior
from .v4_0 import DFIv4_0Behavior

VERSION_BEHAVIOR: Dict[DFIVersion, Type[DFIv2_1Behavior]] = {
    DFIVersion.V2_1: DFIv2_1Behavior,
    DFIVersion.V3_1: DFIv3_1Behavior,
    DFIVersion.V4_0: DFIv4_0Behavior,
    DFIVersion.V5_2: DFIv4_0Behavior,   # rename only; no semantic shift
}


def behavior_for(version: DFIVersion) -> DFIv2_1Behavior:
    """Construct the behavior instance for ``version``.

    Raises:
        KeyError with a helpful message if ``version`` isn't registered —
        adding a new DFI revision is a deliberate code change, not
        something that should fall through silently.
    """
    try:
        cls = VERSION_BEHAVIOR[version]
    except KeyError as exc:
        registered = sorted(v.value for v in VERSION_BEHAVIOR)
        raise KeyError(
            f"No behavior class registered for DFI {version.value}. "
            f"Registered versions: {registered}. Add an entry to "
            f"behaviors/registry.py to support this revision."
        ) from exc
    return cls()

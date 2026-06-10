# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Exceptions used by the per-version behavior classes."""


class NotSupportedInThisVersionError(NotImplementedError):
    """Raised when a behavior method is called for a DFI revision that
    doesn't define that semantic.

    For example, ``DFIv2_1Behavior.disconnect_request()`` raises this
    because the Disconnect Protocol was introduced in v4.0.

    Subclassing :class:`NotImplementedError` rather than ``Exception``
    so that tests / coverage tools can distinguish "feature not yet
    coded" from "version doesn't define this feature."
    """

    def __init__(self, area: str, version: str, introduced_in: str):
        self.area = area
        self.version = version
        self.introduced_in = introduced_in
        super().__init__(
            f"{area} is not defined in DFI {version} "
            f"(introduced in {introduced_in})"
        )

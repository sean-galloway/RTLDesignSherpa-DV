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


class RemovedInThisVersionError(NotSupportedInThisVersionError):
    """Raised when a behavior method is called for a DFI revision that
    dropped that semantic.

    The DFI spec removes whole interfaces, not just adds them: v5.x
    deleted the DFI training interface (training became PHY-internal
    via PHY Managed / PHY Independent Mode) and v6.0 deleted the
    disconnect protocol.
    """

    def __init__(self, area: str, version: str, removed_in: str):
        self.removed_in = removed_in
        # Bypass the parent __init__ message; same attribute contract.
        self.area = area
        self.version = version
        self.introduced_in = ""
        NotImplementedError.__init__(
            self,
            f"{area} was removed from the DFI spec in {removed_in} "
            f"and is not defined in DFI {version}",
        )

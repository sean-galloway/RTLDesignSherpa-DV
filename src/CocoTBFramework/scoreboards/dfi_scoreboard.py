# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI scoreboard — event router for the per-area queues on DFISlavePHY.

The DFI BFM dispatches per-version behavior methods each cycle and
queues events on per-area deques. This scoreboard is the consumer: it
drains the queues, fires registered per-area callbacks, and tallies
counts. No expected/actual comparison for the MVP — that's a future
iteration once we have more use cases.

Usage:

    sb = DFIScoreboard(slave)
    sb.on_error(lambda e: print(f"PHY reported error: code=0x{e.code:x}"))
    sb.on_crc(my_crc_handler)

    # In your test loop:
    while not done:
        await RisingEdge(dut.dfi_clk)
        sb.poll()    # drains new events and fires callbacks

    print(sb.report())   # {area_name: count, …}
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Mapping, Optional

# Maps the scoreboard's public area name to the attribute name on
# DFISlavePHY. The 8 areas match the catalog.
_AREA_TO_QUEUE: Mapping[str, str] = {
    "error":       "error_events",
    "crc":         "crc_events",
    "update":      "update_events",
    "training":    "training_events",
    "ca_parity":   "ca_parity_events",
    "freq_change": "freq_change_events",
    "disconnect":  "disconnect_events",
    "takeover":    "takeover_events",
}


class DFIScoreboard:
    """Event router for DFISlavePHY's per-area queues.

    The scoreboard does **not** spawn its own polling coroutine — the
    user calls :meth:`poll` when they want to drain new events. This
    keeps the scoreboard testable in Tier 1 with mock slaves (no
    cocotb dependency).

    For auto-polling in a cocotb test, wrap ``poll()`` in a coroutine:

        async def polling_loop():
            while True:
                await RisingEdge(clock)
                sb.poll()

        cocotb.start_soon(polling_loop())
    """

    AREAS = tuple(_AREA_TO_QUEUE.keys())

    def __init__(self, slave: Any, log: Optional[logging.Logger] = None):
        """Args:
            slave: a DFISlavePHY (or anything with the per-area event
                attributes — useful for Tier 1 mock testing).
            log: optional logger; if None and slave has ``.log``, that
                is used; otherwise the root logger.
        """
        self.slave = slave
        # `getattr(slave, "log", default)` returns None if slave.log is None;
        # explicit fallback covers both "missing attribute" and "attribute is None".
        self.log = (
            log
            or getattr(slave, "log", None)
            or logging.getLogger(__name__)
        )

        # Per-area callback lists. Each callback is (event) -> None.
        self._callbacks: Dict[str, List[Callable[[Any], None]]] = {
            area: [] for area in self.AREAS
        }

        # Per-area event counts since construction.
        self._counts: Dict[str, int] = {area: 0 for area in self.AREAS}

        # Per-area drain offsets — index of the next event to look at
        # in the slave's deque. Lets poll() be idempotent on already-
        # processed events without removing them from the slave queue.
        self._offsets: Dict[str, int] = {area: 0 for area in self.AREAS}

    # ----- Callback registration -----

    def on_error(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new ErrorEvent."""
        self._callbacks["error"].append(cb)

    def on_crc(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new CRCEvent."""
        self._callbacks["crc"].append(cb)

    def on_update(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new UpdateEvent."""
        self._callbacks["update"].append(cb)

    def on_training(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new TrainingEvent."""
        self._callbacks["training"].append(cb)

    def on_ca_parity(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new CAParityEvent."""
        self._callbacks["ca_parity"].append(cb)

    def on_freq_change(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new FreqChangeEvent."""
        self._callbacks["freq_change"].append(cb)

    def on_disconnect(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new DisconnectEvent."""
        self._callbacks["disconnect"].append(cb)

    def on_takeover(self, cb: Callable[[Any], None]) -> None:
        """Fire ``cb(event)`` for each new TakeoverEvent."""
        self._callbacks["takeover"].append(cb)

    def on_any(self, cb: Callable[[str, Any], None]) -> None:
        """Fire ``cb(area_name, event)`` for every new event in any area.

        Useful for generic logging / coverage / replay harnesses that
        want a single sink.
        """
        for area in self.AREAS:
            # Bind area name into the closure for each per-area callback
            self._callbacks[area].append(
                lambda evt, _area=area: cb(_area, evt)
            )

    # ----- Polling -----

    def poll(self) -> int:
        """Drain new events from every area; fire callbacks; update counts.

        Returns:
            Total number of new events processed across all areas.
        """
        total = 0
        for area, queue_attr in _AREA_TO_QUEUE.items():
            queue = getattr(self.slave, queue_attr, None)
            if queue is None:
                continue
            offset = self._offsets[area]
            queue_len = len(queue)
            if queue_len <= offset:
                continue
            # Snapshot new events; deque slicing through list() avoids
            # mutating the slave's queue.
            new_events = list(queue)[offset:queue_len]
            for evt in new_events:
                self._counts[area] += 1
                for cb in self._callbacks[area]:
                    try:
                        cb(evt)
                    except Exception:
                        # Don't let one bad callback break the rest.
                        self.log.exception(
                            "DFIScoreboard %s callback raised", area,
                        )
                total += 1
            self._offsets[area] = queue_len
        return total

    # ----- Reporting -----

    def report(self) -> Dict[str, int]:
        """Return a fresh dict of per-area event counts."""
        return dict(self._counts)

    def total_events(self) -> int:
        """Return the total number of events processed across all areas."""
        return sum(self._counts.values())

    def reset_counts(self) -> None:
        """Zero the per-area counts without re-draining the queues."""
        for area in self.AREAS:
            self._counts[area] = 0

    def __str__(self) -> str:
        active = {a: n for a, n in self._counts.items() if n}
        return f"DFIScoreboard(total={self.total_events()}, active={active})"

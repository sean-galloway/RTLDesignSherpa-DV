"""Per-ID responses served to waiting calls in request order.

AXI returns responses with the same ID in the order the requests were
issued. The requester BFMs route each B / R beat into a per-ID deque
(``_response_by_id``) from a channel callback, and many calls may wait on
one ID at once (``cocotb.start_soon`` of overlapping transactions). Without
an order among the waiters, whichever call woke first took the beats -- not
necessarily the oldest -- and two same-ID calls could swap responses while
the DUT was correct (RTLDesignSherpa-DV #94).

The fix is a ticket per call, taken where its address is queued for the wire
(``send()`` enqueues synchronously, so ticket order is wire order). A call
may consume beats only while its ticket is at the head of its ID's line.

Usage, in a requester's transaction method::

    ticket = take_ticket(self._waiters_by_id, txn_id)
    try:
        await self.ar_channel.send(ar_packet)
        beats = await wait_turn(self.clock, self._waiters_by_id,
                                self._response_by_id, txn_id, ticket,
                                burst_len, self.timeout_cycles, describe)
    finally:
        release(self._waiters_by_id, txn_id, ticket)
"""
import collections
from typing import Callable, Deque, Dict, List

from cocotb.triggers import RisingEdge


def new_waiters() -> Dict[int, Deque[object]]:
    """The per-ID ticket lines a requester keeps beside ``_response_by_id``."""
    return collections.defaultdict(collections.deque)


def take_ticket(waiters: Dict[int, Deque[object]], txn_id: int) -> object:
    """Join the back of ``txn_id``'s line. Call with no ``await`` between this
    and the ``send()`` that queues the request, so line order is wire order."""
    ticket = object()
    waiters[txn_id].append(ticket)
    return ticket


def release(waiters: Dict[int, Deque[object]], txn_id: int, ticket: object) -> None:
    """Leave the line. Idempotent; call from ``finally`` so a timed-out or
    failed call never blocks the calls behind it."""
    line = waiters.get(txn_id)
    if line is None:
        return
    try:
        line.remove(ticket)
    except ValueError:
        pass
    if not line:
        del waiters[txn_id]


async def wait_turn(clock, waiters: Dict[int, Deque[object]],
                    responses: Dict[int, Deque[object]], txn_id: int,
                    ticket: object, count: int, timeout_cycles: int,
                    describe: Callable[[int, int], str]) -> List[object]:
    """Wait until ``ticket`` heads its ID's line and ``count`` beats are
    queued for that ID, then pop and return them (oldest first) and leave the
    line. ``describe(cycles, received)`` builds the TimeoutError message."""
    queue = responses[txn_id]
    cycles = 0
    try:
        while not (waiters[txn_id] and waiters[txn_id][0] is ticket and len(queue) >= count):
            await RisingEdge(clock)
            cycles += 1
            if cycles > timeout_cycles:
                mine = len(queue) if (waiters[txn_id] and waiters[txn_id][0] is ticket) else 0
                raise TimeoutError(describe(cycles, mine))
        return [queue.popleft() for _ in range(count)]
    finally:
        release(waiters, txn_id, ticket)

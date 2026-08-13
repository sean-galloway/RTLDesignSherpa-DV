"""Streaming CA decode: bus words in, DRAM commands out.

:mod:`ca_map` decodes a command when you already hold all of its edges;
:mod:`ca_dispatch` says what that command means. This module covers the
part in between, which is where the protocols disagree most: **how much
bus a command occupies**.

* DDR5 is SDR and width-matched — one ``dfi_cmdaddr`` word is one CA
  cycle, and a command is 1 or 2 of them (v6.0 Table 18).
* LPDDR5 packs both CA phases of one clock into a single word, and a
  command is exactly one clock (Table 15) — so one word per command.
* LPDDR6 also packs two phases per word, but a command is *two* clocks,
  so it takes **two** words / four edges (Table 16).
* HBM4 carries two independent command streams — row and column — in
  separate lanes of the same 38-bit word (Table 22), so it needs two
  streams fed from split lanes.

:class:`CAStream` handles all of this with one mechanism: the first edge
of a command tells you (via :meth:`CACodec.match`) how many edges to
collect, so the stream buffers until the command is complete and only
then dispatches. Feeding is cycle-driven — a BFM calls
:meth:`feed_word` once per DFI cycle and acts on whatever comes back —
so a command that spans cycles simply produces ``None`` until its last
word arrives.
"""

from typing import List, Optional, Tuple

from .ca_dispatch import CACommandDecoder
from .ca_map import CAMap
from .ca_transport import unpack_ddr_cmdaddr
from .dfi_packet import DRAMCommand
from .hbm_ca import HBM4_EDGE_WIDTH, unpack_hbm4_cmdaddr

Decoded = Tuple[DRAMCommand, dict]


class CAStream:
    """Accumulate CA edges until a command completes, then dispatch it.

    ``ca_width`` is the memory's CA bus width. Words fed to
    :meth:`feed_word` are either one edge (``sdr=True``) or two
    concatenated phases, rising in the low bits (``sdr=False``).

    ``strict`` propagates to the decoder and also governs unrecognized
    head edges: strict raises, non-strict drops the edge and resyncs
    (which is what a monitor attaching mid-command needs).
    """

    def __init__(self, camap: CAMap, ca_width: int, *, sdr: bool = False,
                 strict: bool = True, decoder: Optional[CACommandDecoder] = None):
        self.decoder = decoder or CACommandDecoder(camap, strict=strict)
        self.codec = self.decoder.codec
        self.ca_width = ca_width
        self.sdr = sdr
        self.strict = strict
        self._buf: List[int] = []
        self._need = 0
        #: edges dropped because they matched no command (non-strict only)
        self.resyncs = 0

    # -- feeding -------------------------------------------------------

    def feed_edge(self, edge: int) -> Optional[Decoded]:
        """Feed one CA edge. Returns a command only on the edge that
        completes one (and only if it is not a split first half)."""
        if not self._buf:
            try:
                spec = self.codec.match(edge)
            except ValueError:
                if self.strict:
                    raise
                self.resyncs += 1
                return None
            self._need = spec.n_edges
        self._buf.append(edge)
        if len(self._buf) < self._need:
            return None
        edges, self._buf, self._need = self._buf, [], 0
        return self.decoder.feed(edges)

    def feed_word(self, word: int) -> List[Decoded]:
        """Feed one DFI cycle's CA word. Returns every command completed
        by it — a list because a word can hold two edges, and short
        commands (LPDDR5) can complete twice per word."""
        if self.sdr:
            edges = (word,)
        else:
            phases = unpack_ddr_cmdaddr(self.ca_width, word)
            edges = (phases.rise, phases.fall)
        out = []
        for e in edges:
            got = self.feed_edge(e)
            if got is not None:
                out.append(got)
        return out

    # -- state ---------------------------------------------------------

    @property
    def partial(self) -> bool:
        """True when a command is mid-collection across cycles."""
        return bool(self._buf)

    def reset(self) -> None:
        """Drop partial state — DRAM reset, or a monitor resyncing."""
        self._buf, self._need = [], 0
        self.decoder.reset()


class HBM4CAStreams:
    """HBM4's two independent command streams in one cmdaddr word.

    Each 19-bit edge carries a 10-bit row-command lane and an 8-bit
    column-command lane (v6.0 Table 22), decoded against the row and
    column maps respectively. :meth:`feed_word` returns
    ``(row_commands, column_commands)`` completed by that word.
    """

    def __init__(self, row_map: CAMap, col_map: CAMap, *,
                 strict: bool = True):
        self.row = CAStream(row_map, 10, sdr=True, strict=strict)
        self.col = CAStream(col_map, 8, sdr=True, strict=strict)

    def feed_word(self, word: int) -> Tuple[List[Decoded], List[Decoded]]:
        w = unpack_hbm4_cmdaddr(word)
        rows, cols = [], []
        for edge in (w.rise, w.fall):
            got = self.row.feed_edge(edge.row)
            if got is not None:
                rows.append(got)
            got = self.col.feed_edge(edge.col)
            if got is not None:
                cols.append(got)
        return rows, cols

    def reset(self) -> None:
        self.row.reset()
        self.col.reset()


_ = HBM4_EDGE_WIDTH  # re-exported geometry lives in hbm_ca


def args_to_legacy_addr(args: dict, is_activate: bool) -> Tuple[int, int]:
    """Fold decoded CA args into the ``(bank, addr)`` pair the BFM's
    command handler already speaks.

    The handler predates the CA maps: it takes a row on ACTIVATE and a
    column otherwise, with **bit 10 of addr** carrying auto-precharge
    (RD/WR) or all-banks (PRE) — the DDR convention the LPDDR2 decoder
    already targets. Keeping that contract means the CA path reuses the
    existing, well-tested command handling instead of forking it.
    """
    bank = args.get("bank", 0)
    if is_activate:
        return bank, args.get("row", 0)
    addr = args.get("col", 0)
    if args.get("auto_precharge") or args.get("all_banks"):
        addr |= (1 << 10)
    return bank, addr

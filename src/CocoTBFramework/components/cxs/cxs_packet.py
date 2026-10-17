# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: cxs_packet
# Purpose: CXS flits and packets, and the packing rules between them
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-15
"""CXS flits, packets, and the placement rules that join them.

Two levels, as in the spec:

* :class:`CXSFlit` -- one cycle on the wire (``data``, ``cntl``, ``last``,
  ``prcltype``, ``srcid``, ``tgtid``, ``user``), a framework :class:`Packet`
  so it prints, compares and fills a queue like every other family's beat.
* :class:`CXSPacket` -- one CXS packet (a TLP in CCIX/PCIe terms): a byte
  string of at least 4 bytes and a multiple of 4 (IHI 0079D 4.4), plus the
  stream it belongs to (protocol type, source and target ID) and whether it
  ends with ENDERROR.

:class:`CXSPacketizer` packs packets into flits by the 4.1 rules: a packet
starts at the first free alignment boundary (16 bytes, or 4 with
CXS_START_ALIGNMENT = 4), occupies every following byte until it ends or the
flit ends, continues at byte 0 of the next flit, and ends on a 4-byte
boundary; at most CXSMAXPKTPERFLIT packets have bytes in one flit; all
packets in a flit share one stream. :class:`CXSDepacketizer` reverses it and
reports every rule a received flit breaks.

Byte n of a flit is CXSDATA[8n+7:8n] (Table 4-3: the first packet's first
four bytes are CXSDATA[31:0]).
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from ..shared.field_config import FieldConfig, FieldDefinition
from ..shared.packet import Packet
from .cxs_cntl import CXSCntl
from .cxs_config import CXSConfig


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------
@dataclass
class CXSPacket:
    """One CXS packet: ``payload`` bytes and the stream it rides.

    ``keep_with_next``: the following packet of this stream must stay
    behind it -- CXSLAST stays low after the flit this packet ends in
    (2.3). ``end_error``: the packet ends with ENDERROR.
    """
    payload: bytes
    prcltype: int = 0
    srcid: int = 0
    tgtid: int = 0
    end_error: bool = False
    keep_with_next: bool = False

    def __post_init__(self):
        self.payload = bytes(self.payload)

    @property
    def stream(self):
        """Flits of one stream share these (2.5.2)."""
        return (self.prcltype, self.srcid, self.tgtid)

    def check_size(self):
        n = len(self.payload)
        if n < 4 or n % 4:
            raise ValueError(f"CXS packet of {n} bytes: must be >= 4 and a multiple of 4 (4.4)")

    def __eq__(self, other):
        if not isinstance(other, CXSPacket):
            return NotImplemented
        # keep_with_next is a TX hint, not visible per packet on the wire
        return (self.payload, self.stream, self.end_error) == \
               (other.payload, other.stream, other.end_error)

    def __repr__(self):
        head = self.payload[:8].hex()
        return (f"CXSPacket({len(self.payload)}B {head}{'..' if len(self.payload) > 8 else ''} "
                f"prcl={self.prcltype} src={self.srcid} tgt={self.tgtid}"
                f"{' ENDERROR' if self.end_error else ''})")


# ---------------------------------------------------------------------------
# Flits
# ---------------------------------------------------------------------------
class CXSFlit(Packet):
    """One CXS flit. Fields exist only for the signals the interface has."""

    def __init__(self, cfg: CXSConfig, field_config=None, skip_compare_fields=None, **kwargs):
        object.__setattr__(self, 'cfg', cfg)
        object.__setattr__(self, 'count', kwargs.pop('count', 0))
        if field_config is None:
            field_config = CXSFlit.create_field_config(cfg)
        if skip_compare_fields is None:
            skip_compare_fields = ['start_time', 'end_time', 'count']
        super().__init__(field_config, skip_compare_fields, **kwargs)

    # One FieldConfig per interface configuration, built once. This is where
    # RDS-DV #92 was found (the shared Packet cache keyed on id(field_config)
    # handed a reused id the freed config's 256-bit masks); the cache is fixed,
    # and this stays because rebuilding the config per flit is wasted work.
    _FIELD_CONFIGS: dict = {}

    @staticmethod
    def create_field_config(cfg: CXSConfig) -> FieldConfig:
        cached = CXSFlit._FIELD_CONFIGS.get(cfg)
        if cached is not None:
            return cached
        config = CXSFlit._build_field_config(cfg)
        CXSFlit._FIELD_CONFIGS[cfg] = config
        return config

    @staticmethod
    def _build_field_config(cfg: CXSConfig) -> FieldConfig:
        config = FieldConfig()
        config.add_field(FieldDefinition(
            name="data", bits=cfg.data_width, default=0, format="hex",
            display_width=(cfg.data_width + 3) // 4, description="CXSDATA"))
        if cfg.cntl_width:
            config.add_field(FieldDefinition(
                name="cntl", bits=cfg.cntl_width, default=0, format="hex",
                display_width=(cfg.cntl_width + 3) // 4, description="CXSCNTL"))
        if cfg.has_last:
            config.add_field(FieldDefinition(
                name="last", bits=1, default=1, format="dec", display_width=1,
                description="CXSLAST: flits may be inserted after this one"))
        if cfg.has_prcltype:
            config.add_field(FieldDefinition(
                name="prcltype", bits=3, default=0, format="dec", display_width=1,
                description="CXSPRCLTYPE"))
        if cfg.srcid_width:
            config.add_field(FieldDefinition(
                name="srcid", bits=cfg.srcid_width, default=0, format="hex",
                display_width=(cfg.srcid_width + 3) // 4, description="CXSSRCID"))
        if cfg.tgtid_width:
            config.add_field(FieldDefinition(
                name="tgtid", bits=cfg.tgtid_width, default=0, format="hex",
                display_width=(cfg.tgtid_width + 3) // 4, description="CXSTGTID"))
        if cfg.user_width:
            config.add_field(FieldDefinition(
                name="user", bits=cfg.user_width, default=0, format="hex",
                display_width=(cfg.user_width + 3) // 4, description="CXSUSER"))
        return config

    def get(self, name, default=0):
        return int(self.fields.get(name, default))

    @property
    def control(self) -> CXSCntl:
        return CXSCntl.decode(self.cfg, self.get('cntl'))

    def data_bytes(self) -> bytes:
        return self.get('data').to_bytes(self.cfg.flit_bytes, 'little')

    def formatted(self, compact=False, show_fifo=False):
        if not compact:
            return super().formatted(compact=False, show_fifo=show_fifo)
        c = self.control
        s = f"CXS flit data=0x{self.get('data'):0{self.cfg.flit_bytes * 2}X}"
        if self.cfg.cntl_width:
            s += f" start={list(c.starts)} end={list(c.ends)}"
            if any(c.end_errors):
                s += f" enderr={[int(e) for e in c.end_errors]}"
        for f in ('last', 'prcltype', 'srcid', 'tgtid', 'user'):
            if f in self.fields:
                s += f" {f}={self.get(f)}"
        return s


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------
class CXSPacketizer:
    """Pack :class:`CXSPacket` objects into :class:`CXSFlit` objects.

    Stateless across calls except for an open packet, so feeding packets in
    several calls packs them exactly as one call would; :meth:`flush` emits
    the partly filled last flit.

    ``gap_hook(pos) -> int`` (optional): extra 4-byte gaps to leave before a
    packet with CXS_START_ALIGNMENT = 4, where gaps are permitted (4.1).
    """

    def __init__(self, cfg: CXSConfig, gap_hook: Optional[Callable[[int], int]] = None):
        self.cfg = cfg
        self.gap_hook = gap_hook
        self.flits: List[CXSFlit] = []
        self._new_flit()

    def _new_flit(self):
        self._buf = bytearray(self.cfg.flit_bytes)
        self._pos = 0
        self._starts, self._ends, self._errs = [], [], []
        self._pkts = 0                 # packets with bytes in this flit
        self._stream = None
        self._keep = False             # last packet ended here asks to stay together
        self._open = False

    def _emit(self):
        cfg = self.cfg
        cntl = CXSCntl(self._starts, self._ends, self._errs).encode(cfg)
        fields = {'data': int.from_bytes(bytes(self._buf), 'little')}
        if cfg.cntl_width:
            fields['cntl'] = cntl
        if cfg.has_last:
            fields['last'] = int(not self._open and not self._keep)
        prcl, src, tgt = self._stream or (0, 0, 0)
        if cfg.has_prcltype:
            fields['prcltype'] = prcl
        if cfg.srcid_width:
            fields['srcid'] = src
        if cfg.tgtid_width:
            fields['tgtid'] = tgt
        self.flits.append(CXSFlit(cfg, **fields))
        was_open = self._open
        stream = self._stream
        self._new_flit()
        if was_open:
            self._pkts, self._open, self._stream = 1, True, stream

    def _check_stream(self, pkt):
        """A stream field the interface has no wire for cannot be carried;
        refuse it rather than drop it silently."""
        cfg = self.cfg
        limits = (('prcltype', 3 if cfg.has_prcltype else 0, pkt.prcltype),
                  ('srcid', cfg.srcid_width, pkt.srcid),
                  ('tgtid', cfg.tgtid_width, pkt.tgtid))
        for name, width, value in limits:
            if value >> width:
                raise ValueError(f"CXS packet {name}={value} does not fit this interface "
                                 f"({width}-bit {name}; {cfg.short_name()})")

    def add(self, pkt: CXSPacket):
        cfg = self.cfg
        self._check_stream(pkt)
        if cfg.is_lite:
            # A CXS-Lite packet is the flit itself, any multiple of 8 bits, so
            # the 4-byte packet-size rule of 4.4 does not apply.
            if len(pkt.payload) != cfg.flit_bytes:
                raise ValueError(f"CXS-Lite: a packet is exactly one flit ({cfg.flit_bytes} bytes), "
                                 f"got {len(pkt.payload)}")
            self._buf[:] = pkt.payload
            self._stream = pkt.stream
            self._emit()
            return
        pkt.check_size()
        if self._open:
            raise RuntimeError("CXSPacketizer: previous packet still open")
        # Where can it start in the current flit?
        align = cfg.start_align
        start = -(-self._pos // align) * align
        if align == 4 and self.gap_hook is not None and self._pos:
            start += 4 * max(0, int(self.gap_hook(start)))
        full = (start >= cfg.flit_bytes or self._pkts >= cfg.max_pkt_per_flit
                or len(self._starts) >= cfg.max_pkt_per_flit
                or (self._stream is not None and self._stream != pkt.stream))
        if full and (self._pkts or self._pos):
            self._emit()
            start = 0
        self._stream = pkt.stream
        self._starts.append(start // align)
        self._pkts += 1
        remaining = memoryview(pkt.payload)
        pos = start
        while True:
            room = cfg.flit_bytes - pos
            take = min(room, len(remaining))
            self._buf[pos:pos + take] = remaining[:take]
            remaining = remaining[take:]
            pos += take
            if not remaining:
                self._ends.append((pos - 4) // 4)
                self._errs.append(pkt.end_error)
                self._pos = pos
                self._keep = pkt.keep_with_next
                self._open = False
                if pos >= cfg.flit_bytes:
                    self._emit()
                return
            self._open = True
            self._emit()               # flit full, packet continues at byte 0
            pos = 0

    def add_all(self, packets):
        for p in packets:
            self.add(p)
        return self

    def flush(self) -> List[CXSFlit]:
        """Emit the partly filled flit, if any, and return every flit so far."""
        if self._pkts or self._pos:
            self._emit()
        out, self.flits = self.flits, []
        return out


class CXSDepacketizer:
    """Rebuild :class:`CXSPacket` objects from received flits, checking the
    placement rules on the way. Feed flits with :meth:`push`; finished
    packets collect in :attr:`packets` and go to ``callback`` if given.
    ``violations`` lists every broken rule with the flit ordinal.

    Packets are framed PER STREAM: a stream is the flits sharing
    (CXSPRCLTYPE, CXSSRCID, CXSTGTID), and flits of different streams may
    interleave (IHI 0079D 2.5.2), so each stream keeps its own open packet.
    With CXSCONTINUOUSDATA a flit of another stream may not be inserted
    while a packet is open and CXSLAST is low (absent CXSLAST counts as low
    while a packet is open, 2.3)."""

    def __init__(self, cfg: CXSConfig, callback: Optional[Callable[[CXSPacket], None]] = None):
        self.cfg = cfg
        self.callback = callback
        self.packets: List[CXSPacket] = []
        self.violations: List[str] = []
        self.flits = 0
        self._open: Dict[tuple, bytearray] = {}     # stream -> bytes of its open packet
        self._prev_last = 1
        self._prev_stream = None

    def _violation(self, msg):
        self.violations.append(f"flit {self.flits}: {msg}")

    def _finish(self, buf, stream, err):
        pkt = CXSPacket(bytes(buf), *stream, end_error=bool(err))
        if not self.cfg.is_lite and (len(buf) < 4 or len(buf) % 4):
            self._violation(f"packet of {len(buf)} bytes (4.4)")
        self.packets.append(pkt)
        if self.callback:
            self.callback(pkt)

    def push(self, flit: CXSFlit):
        cfg = self.cfg
        self.flits += 1
        stream = (flit.get('prcltype'), flit.get('srcid'), flit.get('tgtid'))
        data = flit.data_bytes()
        if cfg.is_lite:
            self._finish(data, stream, False)
            return
        if cfg.continuous and self._prev_stream is not None and stream != self._prev_stream:
            last_low = (not self._prev_last) if cfg.has_last else bool(self._open)
            if last_low and self._open:
                self._violation("stream changed while CXSLAST was low with CXSCONTINUOUSDATA")
        c = flit.control
        cur = self._open.get(stream)
        for v in c.violations(cfg, open_before=cur is not None):
            self._violation(v)
        ends = list(zip(c.end_bytes(), c.end_errors))
        if cur is not None:
            if ends:
                e, err = ends.pop(0)
                cur += data[:e + 1]
                self._finish(cur, stream, err)
                del self._open[stream]
            elif not c.starts:
                cur += data
        for st in c.start_bytes(cfg):
            if ends:
                e, err = ends.pop(0)
                self._finish(data[st:e + 1], stream, err)
            else:
                self._open[stream] = bytearray(data[st:])
        if cfg.has_last:
            last = flit.get('last')
            if last and stream in self._open:
                self._violation("CXSLAST high with a packet still open (2.3)")
            self._prev_last = last
        self._prev_stream = stream

    @property
    def in_packet(self):
        """Some stream has a packet open."""
        return bool(self._open)

    def open_streams(self):
        return sorted(self._open)

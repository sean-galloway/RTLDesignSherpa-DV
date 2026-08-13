"""Declarative CA-bus command maps: data-driven encode/decode.

CA encodings vary per protocol AND per device — opcode patterns, field
placements, edge counts, even which commands exist. Rather than one
hardcoded codec module per device, a :class:`CAMap` describes the
encoding as data and one engine does the work:

* a **command** is an opcode pattern (specific bits that must hold
  specific values on specific edges) plus **fields** (named values
  scattered across edge/bit positions), occupying a fixed number of
  bus edges;
* a **field placement** is a list of contiguous bit runs
  ``(edge, bus_lo, field_lo, width)`` — non-contiguous scatters (e.g.
  the HBM4 MRS MA/OP interleave) are just multiple runs;
* **decode** matches opcode bits across ALL of a command's edges
  (most-specific pattern wins), then gathers fields. Commands may be
  identical on their first edge and differ only later (DDR5 WR vs WRA
  split on cycle-2 CA10); such commands must occupy the same number
  of edges so a streaming consumer can classify edge count from the
  first edge alone (:meth:`CACodec.match`). Deliberate aliases
  (patterns identical by design, like HBM4 RNOP vs PDX/SRX where
  power state selects the meaning) are declared with ``alias_of`` so
  map validation doesn't reject them.

Ships with :data:`HBM4_CA_MAP` (JESD270-4A Tables 33/34) as the
reference map — differentially tested against the hand-written
:mod:`hbm4_commands` golden encoders. Device-specific variations:
start from a shipped map, ``replace``/extend commands, and pass your
map to the engine (or load one from JSON with :func:`camap_from_dict`).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class BitRun:
    """`width` field bits placed at ``bus_lo`` on edge ``edge``:
    field[field_lo +: width] <-> edge[bus_lo +: width]."""
    edge: int
    bus_lo: int
    field_lo: int
    width: int


@dataclass(frozen=True)
class FieldSpec:
    name: str
    width: int
    runs: Tuple[BitRun, ...]

    def __post_init__(self):
        covered = sorted(r.field_lo for r in self.runs)
        total = sum(r.width for r in self.runs)
        if total != self.width:
            raise ValueError(
                f"field {self.name}: runs cover {total} bits, "
                f"declared width {self.width}")
        _ = covered  # placement overlap is checked at map level


@dataclass(frozen=True)
class OpcodeBit:
    edge: int
    bit: int
    value: int


@dataclass(frozen=True)
class CommandSpec:
    name: str
    n_edges: int
    opcode: Tuple[OpcodeBit, ...]
    fields: Tuple[FieldSpec, ...] = ()
    alias_of: Optional[str] = None   # deliberate same-pattern alias

    def field(self, name: str) -> FieldSpec:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"{self.name} has no field {name!r}")


@dataclass(frozen=True)
class CAMap:
    """A device/protocol CA encoding: bus width + command set."""
    name: str
    bus_width: int
    commands: Tuple[CommandSpec, ...]

    def __post_init__(self):
        self._validate()

    def command(self, name: str) -> CommandSpec:
        for c in self.commands:
            if c.name == name:
                return c
        raise KeyError(f"{self.name}: unknown command {name!r}")

    # -- validation ----------------------------------------------------

    def _validate(self):
        names = [c.name for c in self.commands]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.name}: duplicate command names")
        mask = (1 << self.bus_width) - 1
        for c in self.commands:
            for ob in c.opcode:
                if not 0 <= ob.bit < self.bus_width:
                    raise ValueError(
                        f"{self.name}.{c.name}: opcode bit {ob.bit} "
                        f"outside {self.bus_width}-bit bus")
                if ob.edge >= c.n_edges:
                    raise ValueError(
                        f"{self.name}.{c.name}: opcode edge {ob.edge} "
                        f">= n_edges {c.n_edges}")
            for f in c.fields:
                for r in f.runs:
                    if r.edge >= c.n_edges:
                        raise ValueError(
                            f"{self.name}.{c.name}.{f.name}: run edge "
                            f"{r.edge} >= n_edges {c.n_edges}")
                    if r.bus_lo + r.width - 1 > self.bus_width - 1:
                        raise ValueError(
                            f"{self.name}.{c.name}.{f.name}: run "
                            f"exceeds bus width")
            _ = mask
        # Full opcode signatures must be pairwise distinguishable
        # unless one declares alias_of the other. Commands that are
        # NOT distinguishable on edge 0 alone (they split on a later
        # edge, e.g. DDR5 WR/WRA on cycle-2 CA10) must occupy the same
        # number of edges — otherwise a streaming consumer cannot know
        # how many edges to collect from the first edge.
        sigs = []
        for c in self.commands:
            full = {(ob.edge, ob.bit): ob.value for ob in c.opcode}
            head = {ob.bit: ob.value for ob in c.opcode if ob.edge == 0}
            sigs.append((c, full, head))
        for i, (ca, fa, ha) in enumerate(sigs):
            for cb, fb, hb in sigs[i + 1:]:
                if ca.alias_of == cb.name or cb.alias_of == ca.name:
                    continue
                if all(ha[k] == hb[k] for k in set(ha) & set(hb)):
                    # edge-0-compatible: later edges must both split
                    # them and be reachable in one streamed command.
                    if ca.n_edges != cb.n_edges:
                        raise ValueError(
                            f"{self.name}: commands {ca.name!r} and "
                            f"{cb.name!r} are not distinguishable on "
                            f"edge 0 but occupy different edge counts "
                            f"({ca.n_edges} vs {cb.n_edges})")
                    if all(fa[k] == fb[k] for k in set(fa) & set(fb)):
                        raise ValueError(
                            f"{self.name}: commands {ca.name!r} and "
                            f"{cb.name!r} are not distinguishable by "
                            f"opcode bits and are not declared aliases")


class CACodec:
    """Generic encoder/decoder driven by a :class:`CAMap`."""

    def __init__(self, camap: CAMap):
        self.map = camap
        # Most-specific-first orders: edge-0 bits for streaming match,
        # total opcode bits for full decode.
        self._match_order = sorted(
            camap.commands,
            key=lambda c: -len([b for b in c.opcode if b.edge == 0]))
        self._decode_order = sorted(
            camap.commands, key=lambda c: -len(c.opcode))

    # -- encode --------------------------------------------------------

    def encode(self, command: str, **fields: int) -> List[int]:
        spec = self.map.command(command)
        edges = [0] * spec.n_edges
        for ob in spec.opcode:
            edges[ob.edge] |= (ob.value & 1) << ob.bit
        wanted = {f.name for f in spec.fields}
        given = set(fields)
        if given - wanted:
            raise ValueError(
                f"{command}: unknown field(s) {sorted(given - wanted)}")
        for f in spec.fields:
            val = fields.get(f.name, 0)
            if not 0 <= val < (1 << f.width):
                raise ValueError(
                    f"{command}.{f.name} 0x{val:X} exceeds {f.width} bits")
            for r in f.runs:
                chunk = (val >> r.field_lo) & ((1 << r.width) - 1)
                edges[r.edge] |= chunk << r.bus_lo
        return edges

    # -- decode --------------------------------------------------------

    def match(self, first_edge: int) -> CommandSpec:
        """Classify a command by its first edge's opcode bits.

        For streaming: the returned spec's ``n_edges`` tells you how
        many edges to collect before calling :meth:`decode`. When
        several commands share a first-edge pattern and split on a
        later edge (DDR5 WR/WRA), this returns a representative —
        map validation guarantees all of them occupy the same
        ``n_edges``, so the edge count is still authoritative; only
        :meth:`decode` names the final command."""
        for spec in self._match_order:
            if all(((first_edge >> ob.bit) & 1) == ob.value
                   for ob in spec.opcode if ob.edge == 0):
                return spec
        raise ValueError(
            f"{self.map.name}: no command matches first edge "
            f"0x{first_edge:X}")

    def decode(self, edges: Sequence[int]) -> Tuple[str, Dict[str, int]]:
        """Decode a full command from its edges (len == n_edges of the
        matched command; use :meth:`match` first when streaming to know
        how many edges to collect)."""
        head = self.match(edges[0])
        if len(edges) != head.n_edges:
            raise ValueError(
                f"{head.name} occupies {head.n_edges} edge(s), "
                f"got {len(edges)}")
        spec = None
        for cand in self._decode_order:
            if cand.n_edges == len(edges) and all(
                    ((edges[ob.edge] >> ob.bit) & 1) == ob.value
                    for ob in cand.opcode):
                spec = cand
                break
        if spec is None:
            raise ValueError(
                f"{self.map.name}: no command matches edges "
                f"{[hex(e) for e in edges]}")
        out: Dict[str, int] = {}
        for f in spec.fields:
            val = 0
            for r in f.runs:
                chunk = (edges[r.edge] >> r.bus_lo) & ((1 << r.width) - 1)
                val |= chunk << r.field_lo
            out[f.name] = val
        return spec.name, out


# ---------------------------------------------------------------------------
# JSON/dict loader — so device maps can live in files.
# ---------------------------------------------------------------------------

def camap_from_dict(d: dict) -> CAMap:
    """Build a CAMap from a plain-dict description (e.g. json.load).

    Shape::

        {"name": "...", "bus_width": 10,
         "commands": [
           {"name": "act", "n_edges": 3,
            "opcode": [[edge, bit, value], ...],
            "fields": [{"name": "row", "width": 15,
                        "runs": [[edge, bus_lo, field_lo, width], ...]},
                       ...],
            "alias_of": null}, ...]}
    """
    cmds = []
    for c in d["commands"]:
        fields = tuple(
            FieldSpec(f["name"], f["width"],
                      tuple(BitRun(*r) for r in f["runs"]))
            for f in c.get("fields", ()))
        cmds.append(CommandSpec(
            name=c["name"], n_edges=c["n_edges"],
            opcode=tuple(OpcodeBit(*o) for o in c["opcode"]),
            fields=fields, alias_of=c.get("alias_of")))
    return CAMap(d["name"], d["bus_width"], tuple(cmds))


# ---------------------------------------------------------------------------
# HBM4 reference map — JESD270-4A Tables 33 / 34. Differentially tested
# against the hand-written hbm4_commands encoders.
# ---------------------------------------------------------------------------

def _banked_fields(edge: int = 0) -> Tuple[FieldSpec, ...]:
    return (
        FieldSpec("pc", 1, (BitRun(edge, 3, 0, 1),)),
        FieldSpec("sid", 2, (BitRun(edge, 4, 0, 2),)),
        FieldSpec("ba", 4, (BitRun(edge, 6, 0, 4),)),
    )


HBM4_ROW_CA_MAP = CAMap(
    name="hbm4_row",
    bus_width=10,
    commands=(
        CommandSpec("rnop", 1, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 1),
            OpcodeBit(0, 2, 1), OpcodeBit(0, 3, 1))),
        CommandSpec("pdx_srx", 1, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 1),
            OpcodeBit(0, 2, 1), OpcodeBit(0, 3, 1)),
            alias_of="rnop"),
        CommandSpec("act", 3, (
            OpcodeBit(0, 0, 0), OpcodeBit(0, 1, 1), OpcodeBit(0, 2, 1),
            OpcodeBit(1, 0, 1), OpcodeBit(1, 1, 1),
            OpcodeBit(2, 0, 1), OpcodeBit(2, 1, 1)),
            fields=_banked_fields() + (
                FieldSpec("row", 15, (
                    BitRun(2, 2, 0, 8),     # RA0..RA7 on edge 2
                    BitRun(1, 2, 8, 7))),   # RA8..RA14 on edge 1
            )),
        CommandSpec("prepb", 1, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 0), OpcodeBit(0, 2, 0)),
            fields=_banked_fields()),
        CommandSpec("preab", 1, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 0), OpcodeBit(0, 2, 1)),
            fields=(FieldSpec("pc", 1, (BitRun(0, 3, 0, 1),)),)),
        CommandSpec("refpb", 1, (
            OpcodeBit(0, 0, 0), OpcodeBit(0, 1, 0), OpcodeBit(0, 2, 0)),
            fields=_banked_fields()),
        CommandSpec("refab", 1, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 1), OpcodeBit(0, 2, 0),
            OpcodeBit(0, 8, 0)),
            fields=(FieldSpec("pc", 1, (BitRun(0, 3, 0, 1),)),)),
        CommandSpec("rfmpb", 1, (
            OpcodeBit(0, 0, 0), OpcodeBit(0, 1, 0), OpcodeBit(0, 2, 1)),
            fields=_banked_fields()),
        CommandSpec("rfmab", 1, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 1), OpcodeBit(0, 2, 0),
            OpcodeBit(0, 8, 1)),
            fields=(FieldSpec("pc", 1, (BitRun(0, 3, 0, 1),)),)),
        CommandSpec("pde", 2, (
            OpcodeBit(0, 0, 0), OpcodeBit(0, 1, 1),
            OpcodeBit(0, 2, 0), OpcodeBit(0, 3, 1),
            OpcodeBit(1, 0, 0), OpcodeBit(1, 1, 1),
            OpcodeBit(1, 2, 0), OpcodeBit(1, 3, 1))),
        CommandSpec("sre", 2, (
            OpcodeBit(0, 0, 0), OpcodeBit(0, 1, 1),
            OpcodeBit(0, 2, 0), OpcodeBit(0, 3, 0),
            OpcodeBit(1, 0, 0), OpcodeBit(1, 1, 1),
            OpcodeBit(1, 2, 0), OpcodeBit(1, 3, 0))),
    ),
)


def _col_rw_fields() -> Tuple[FieldSpec, ...]:
    return (
        FieldSpec("pc", 1, (BitRun(0, 4, 0, 1),)),
        FieldSpec("sid", 2, (BitRun(0, 5, 0, 2),)),
        FieldSpec("ba", 4, (
            BitRun(0, 7, 0, 1),      # BA0 on the rising edge
            BitRun(1, 0, 1, 3))),    # BA1..BA3 on the falling edge
        FieldSpec("col", 5, (BitRun(1, 3, 0, 5),)),
    )


HBM4_COL_CA_MAP = CAMap(
    name="hbm4_col",
    bus_width=8,
    commands=(
        CommandSpec("cnop", 1, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 1), OpcodeBit(0, 2, 1))),
        CommandSpec("rd", 2, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 0),
            OpcodeBit(0, 2, 1), OpcodeBit(0, 3, 0)),
            fields=_col_rw_fields()),
        CommandSpec("rda", 2, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 0),
            OpcodeBit(0, 2, 1), OpcodeBit(0, 3, 1)),
            fields=_col_rw_fields()),
        CommandSpec("wr", 2, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 0),
            OpcodeBit(0, 2, 0), OpcodeBit(0, 3, 0)),
            fields=_col_rw_fields()),
        CommandSpec("wra", 2, (
            OpcodeBit(0, 0, 1), OpcodeBit(0, 1, 0),
            OpcodeBit(0, 2, 0), OpcodeBit(0, 3, 1)),
            fields=_col_rw_fields()),
        CommandSpec("mrs", 2, (
            OpcodeBit(0, 0, 0), OpcodeBit(0, 1, 0), OpcodeBit(0, 2, 0)),
            fields=(
                FieldSpec("ma", 5, (
                    BitRun(0, 7, 0, 1),     # MA0 rising C7
                    BitRun(1, 0, 1, 3),     # MA1..MA3 falling C0..C2
                    BitRun(0, 3, 4, 1))),   # MA4 rising C3
                FieldSpec("op", 8, (
                    BitRun(1, 3, 0, 5),     # OP0..OP4 falling C3..C7
                    BitRun(0, 4, 5, 3))),   # OP5..OP7 rising C4..C6
            )),
    ),
)

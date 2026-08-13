"""CA map -> BFM command dispatch.

:mod:`ca_map` and the per-protocol maps answer "what bits are on the
bus". This module answers the next question: "what does that mean to
the DRAM state model". It turns a decoded CA command into the BFM's
canonical ``(DRAMCommand, args)`` pair — the same contract
:func:`lpddr_ca.decode_lpddr2_ca` already returns, so
:class:`dfi_slave_phy.DFISlavePHY` and :class:`dfi_monitor.DFIMonitor`
consume every protocol through one interface.

Three things make this more than a lookup table:

* **Split commands.** LPDDR5 and LPDDR6 issue ACTIVATE as an ACT-1 /
  ACT-2 pair carrying different halves of the row address, and MODE
  REGISTER WRITE as MRW-1 (address) / MRW-2 (opcode). Other commands
  may legally sit between the halves (JESD209-5C note 4), so the
  decoder latches the first half and only emits a command when the
  second arrives. :meth:`CACommandDecoder.feed` returns ``None`` for
  a first half.
* **Bank composition.** Protocols split the bank index across bank
  and bank-group fields of varying widths. The flat index is
  ``(bg << ba_width) | ba``, with ``ba_width`` read from the map
  itself rather than hardcoded per protocol.
* **Auto-precharge and all-banks reach the model two ways.** DDR5 and
  HBM4 encode them as distinct commands (RDA, PREab); LPDDR5/6 encode
  them as operand bits (AP, AB) on a shared command. Both arrive as
  ``args['auto_precharge']`` / ``args['all_banks']`` with the
  matching :class:`DRAMCommand`.

Translations are explicit per map — no prefix guessing. A command not
in the table is a decode the state model has no opinion about (CAS,
MPC, FIFO/calibration commands) and maps to ``NOP``.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .ca_map import CACodec, CAMap
from .dfi_packet import DRAMCommand

# Fields that are device/channel selectors rather than addresses. They
# pass through to args untouched so a caller can filter on them.
PASSTHROUGH_FIELDS = ("pc", "sid", "sc", "cid", "dbg", "sb0", "rfm",
                      "bc", "rir", "odt", "bl", "wr_partial", "cw",
                      "dsm", "pd", "b4", "ws", "ws_off")


@dataclass(frozen=True)
class Translation:
    """What a map command means to the state model.

    ``command`` is the canonical code. ``auto_precharge`` / ``all_banks``
    force the flag on for commands that encode it in the name (RDA,
    PREab); when the map carries an ``ap``/``ab`` operand instead, the
    field value decides. ``pairs_with`` marks a first-half command that
    latches state and emits nothing until its partner arrives.
    """
    command: DRAMCommand
    auto_precharge: bool = False
    all_banks: bool = False
    is_mrr: bool = False
    pairs_with: Optional[str] = None


def _t(cmd: DRAMCommand, **kw) -> Translation:
    return Translation(cmd, **kw)


# --- per-map translation tables -------------------------------------------

_DDR5 = {
    "act": _t(DRAMCommand.ACT),
    "rd": _t(DRAMCommand.RD),
    "rda": _t(DRAMCommand.RDA, auto_precharge=True),
    "wr": _t(DRAMCommand.WR),
    "wra": _t(DRAMCommand.WRA, auto_precharge=True),
    "wrp": _t(DRAMCommand.WR),
    "wrpa": _t(DRAMCommand.WRA, auto_precharge=True),
    "preab": _t(DRAMCommand.PREA, all_banks=True),
    "presb": _t(DRAMCommand.PRE),
    "prepb": _t(DRAMCommand.PRE),
    "refab": _t(DRAMCommand.REF, all_banks=True),
    "refsb": _t(DRAMCommand.REF),
    "rfmab": _t(DRAMCommand.REF, all_banks=True),
    "rfmsb": _t(DRAMCommand.REF),
    "mrw": _t(DRAMCommand.MRS),
    "mrr": _t(DRAMCommand.MRS, is_mrr=True),
    "sre": _t(DRAMCommand.SRE),
    "sref": _t(DRAMCommand.SRE),
    "pde": _t(DRAMCommand.PDE),
    "nop": _t(DRAMCommand.NOP),
}

_HBM4_ROW = {
    "act": _t(DRAMCommand.ACT),
    "prepb": _t(DRAMCommand.PRE),
    "preab": _t(DRAMCommand.PREA, all_banks=True),
    "refpb": _t(DRAMCommand.REF),
    "refab": _t(DRAMCommand.REF, all_banks=True),
    "rfmpb": _t(DRAMCommand.REF),
    "rfmab": _t(DRAMCommand.REF, all_banks=True),
    "pde": _t(DRAMCommand.PDE),
    "sre": _t(DRAMCommand.SRE),
    "rnop": _t(DRAMCommand.NOP),
    "pdx_srx": _t(DRAMCommand.PDX),
}

_HBM4_COL = {
    "rd": _t(DRAMCommand.RD),
    "rda": _t(DRAMCommand.RDA, auto_precharge=True),
    "wr": _t(DRAMCommand.WR),
    "wra": _t(DRAMCommand.WRA, auto_precharge=True),
    "mrs": _t(DRAMCommand.MRS),
    "cnop": _t(DRAMCommand.NOP),
}

_LPDDR5 = {
    "act1": _t(DRAMCommand.ACT, pairs_with="act2"),
    "act2": _t(DRAMCommand.ACT),
    "pre": _t(DRAMCommand.PRE),
    "ref": _t(DRAMCommand.REF),
    "rfm": _t(DRAMCommand.REF),
    "drfm": _t(DRAMCommand.REF),
    "mwr": _t(DRAMCommand.WR),
    "wr16": _t(DRAMCommand.WR),
    "wr32": _t(DRAMCommand.WR),
    "rd16": _t(DRAMCommand.RD),
    "rd32": _t(DRAMCommand.RD),
    "mrw1": _t(DRAMCommand.MRS, pairs_with="mrw2"),
    "mrw2": _t(DRAMCommand.MRS),
    "mrr": _t(DRAMCommand.MRS, is_mrr=True),
    "sre": _t(DRAMCommand.SRE),
    "srx": _t(DRAMCommand.SRX),
    "pde": _t(DRAMCommand.PDE),
    "nop": _t(DRAMCommand.NOP),
}

_LPDDR6 = {
    "act1": _t(DRAMCommand.ACT, pairs_with="act2"),
    "act2": _t(DRAMCommand.ACT),
    "pre": _t(DRAMCommand.PRE),
    "ref": _t(DRAMCommand.REF),
    "wr_s": _t(DRAMCommand.WR),
    "wr_l": _t(DRAMCommand.WR),
    "rd_s": _t(DRAMCommand.RD),
    "rd_l": _t(DRAMCommand.RD),
    "mrw1": _t(DRAMCommand.MRS, pairs_with="mrw2"),
    "mrw2": _t(DRAMCommand.MRS),
    "mrr": _t(DRAMCommand.MRS, is_mrr=True),
    "sre": _t(DRAMCommand.SRE),
    "srx": _t(DRAMCommand.SRX),
    "pde": _t(DRAMCommand.PDE),
    "nop": _t(DRAMCommand.NOP),
}

#: Translation tables by map name. LPDDR5's three bank organizations
#: share one table — organization changes field widths, not meanings.
TRANSLATIONS: Dict[str, Dict[str, Translation]] = {
    "ddr5": _DDR5,
    "hbm4_row": _HBM4_ROW,
    "hbm4_col": _HBM4_COL,
    "lpddr5_bg": _LPDDR5,
    "lpddr5_16b": _LPDDR5,
    "lpddr5_8b": _LPDDR5,
    "lpddr6": _LPDDR6,
}


@dataclass
class _Pending:
    """Latched first half of a split command."""
    name: str
    fields: Dict[str, int] = field(default_factory=dict)


class CACommandDecoder:
    """Decode CA edges into ``(DRAMCommand, args)`` for the state model.

    ``strict`` (default) raises when a second-half command arrives with
    no latched first half — a real protocol violation worth surfacing
    from a slave BFM. Monitors that may attach mid-stream should pass
    ``strict=False``, which drops the orphan and returns ``None``.
    """

    def __init__(self, camap: CAMap, *, strict: bool = True,
                 translations: Optional[Dict[str, Translation]] = None):
        self.map = camap
        self.codec = CACodec(camap)
        self.strict = strict
        if translations is None:
            try:
                translations = TRANSLATIONS[camap.name]
            except KeyError:
                raise KeyError(
                    f"no translation table for map {camap.name!r}; pass "
                    f"translations= to define one") from None
        self.translations = translations
        self._pending: Optional[_Pending] = None

    # -- helpers -------------------------------------------------------

    def _field_width(self, name: str, *commands: str) -> int:
        """Width of field ``name`` as declared by the first of
        ``commands`` that carries it. Split commands merge fields from
        two different specs, so the owner is not always the command
        being emitted — an ACT-2 carries no bank fields, they came from
        the latched ACT-1."""
        for cmd in commands:
            for f in self.map.command(cmd).fields:
                if f.name == name:
                    return f.width
        return 0

    def _bank(self, fields: Dict[str, int], *owners: str) -> Optional[int]:
        if "ba" not in fields:
            return None
        if "bg" in fields:
            width = self._field_width("ba", *owners)
            return (fields["bg"] << width) | fields["ba"]
        return fields["ba"]

    # -- main entry ----------------------------------------------------

    def feed(self, edges) -> Optional[Tuple[DRAMCommand, Dict[str, int]]]:
        """Decode one command's edges.

        Returns ``None`` when the edges are the first half of a split
        command (its state is latched until the partner arrives).
        """
        name, fields = self.codec.decode(edges)
        tr = self.translations.get(name)
        if tr is None:
            return DRAMCommand.NOP, {}

        if tr.pairs_with is not None:
            self._pending = _Pending(name, dict(fields))
            return None

        merged = dict(fields)
        owners = [name]
        partner_of = self._partner_source(name)
        if partner_of is not None:
            pending = self._pending
            self._pending = None
            if pending is None or pending.name != partner_of:
                if self.strict:
                    raise ValueError(
                        f"{self.map.name}: {name!r} with no preceding "
                        f"{partner_of!r}")
                return None
            # First half carries the bank/selector fields and the row
            # high bits; second half carries the rest.
            merged = {**pending.fields, **merged}
            owners.append(pending.name)

        return self._to_args(name, tr, merged, owners)

    def _partner_source(self, name: str) -> Optional[str]:
        for src, tr in self.translations.items():
            if tr.pairs_with == name:
                return src
        return None

    def _to_args(self, name: str, tr: Translation, fields: Dict[str, int],
                 owners) -> Tuple[DRAMCommand, Dict[str, int]]:
        args: Dict[str, int] = {}
        cmd = tr.command

        bank = self._bank(fields, *owners)
        if bank is not None:
            args["bank"] = bank

        # Row: either one field, or the halves of a split ACTIVATE.
        if "row" in fields:
            args["row"] = fields["row"]
        elif "row_lo" in fields:
            shift = self._field_width("row_lo", *owners)
            args["row"] = (fields.get("row_hi", 0) << shift) | fields["row_lo"]

        if "col" in fields:
            args["col"] = fields["col"]

        auto = tr.auto_precharge or bool(fields.get("ap", 0))
        if auto:
            args["auto_precharge"] = True
            if cmd is DRAMCommand.RD:
                cmd = DRAMCommand.RDA
            elif cmd is DRAMCommand.WR:
                cmd = DRAMCommand.WRA

        all_banks = tr.all_banks or bool(fields.get("ab", 0))
        if all_banks:
            args["all_banks"] = True
            if cmd is DRAMCommand.PRE:
                cmd = DRAMCommand.PREA

        # Mode register: field names differ (ma / mra), operand is op.
        mr_addr = fields.get("ma", fields.get("mra"))
        if mr_addr is not None:
            args["mr_addr"] = mr_addr
        if "op" in fields and cmd is DRAMCommand.MRS:
            args["mr_data"] = fields["op"]
        if tr.is_mrr:
            args["is_mrr"] = True

        for key in PASSTHROUGH_FIELDS:
            if key in fields:
                args[key] = fields[key]

        return cmd, args

    def reset(self) -> None:
        """Drop any latched first half (e.g. on DRAM reset)."""
        self._pending = None

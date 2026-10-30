<!-- RTL Design Sherpa Documentation Header -->
<table>
<tr>
<td width="80">
  <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">
    <img src="https://raw.githubusercontent.com/sean-galloway/RTLDesignSherpa/main/docs/logos/Logo_200px.png" alt="RTL Design Sherpa" width="70">
  </a>
</td>
<td>
  <strong>CocoTB Framework</strong> · <em>Verification Infrastructure for RTL Testing</em><br>
  <sub>
    <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">GitHub</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/docs/DOCUMENTATION_INDEX.md">Documentation Index</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/LICENSE">MIT License</a>
  </sub>
</td>
</tr>
</table>

---

<!-- End Header -->

# CHI Configuration, Flits and Encodings

## CHIConfig

A frozen dataclass, one per port; `with_(**changes)` returns a modified copy and `validate()` returns it or raises naming the broken rule. `node_type` is the node the **BFM** plays, not the DUT: a `CHIRequestNode` with `node_type=RN_F` drives a Home-side DUT.

| Field | Spec property | Default |
|---|---|---|
| `issue` | (issue; `CHIIssue`, 'E'-'H' or 5-8) | H |
| `node_type` | B13.6 node interface (`NodeType`; 'RN-F', 'rn_f' and `NodeType.RN_F` all coerce) | RN-F |
| `nodeid_width` | B16.1.12 NodeID_Width | 7 |
| `addr_width` | B16.1.11 Req_Addr_Width (RAW) | 44 |
| `data_width` | B16.1.13 Data_Width (DW) | 128 |
| `req_rsvdc_width` / `dat_rsvdc_width` | B16.1.28 / B16.1.29 Req_RSVDC_Width (Y) / Dat_RSVDC_Width | 0 |
| `mpam_width` | B16.1.9 MPAM_Support (M = 0, 12, 15) | 0 |
| `pbha_width` | B16.1.19 PBHA_Support (PB = 0, 4) | 0 |
| `mecid_width` | B16.1.26 MECID_Width (E = 0, 16) | 0 |
| `streamid_width` | RME-CDA StreamID (R = 0, 16; shares the REQ slot with MECID) | 0 |
| `secsid1_width` | RME-CDA SecSID1 (S = 0, 1) | 0 |
| `data_check` | B16.1.6 Data_Check (DC = DW/8 when set) | False |
| `poison` | B16.1.4 Data_Poison (P = DW/64 when set) | False |
| `max_lcredit` | B14.2.1.1 L-Credits per channel, 1 to 15 | 15 |
| `link_control` | `LINKACTIVEREQ` / `ACK` pair present | True |
| `sactive` | `TXSACTIVE` / `RXSACTIVE` present | True |

`config_error()` returns 0 when legal, else the first broken rule; `CONFIG_RULES` maps the number to its sentence so a test can assert on it. `tests/unit/test_chi_config.py` drives one illegal value per rule and checks the message says `rule N:`.

| Rule | Requirement |
|---|---|
| 1 | issue must be H (the only issue with an on-disk spec; G flit widths differ) |
| 2 | NodeID_Width must be 7 to 16 (Table B16.11) |
| 3 | Req_Addr_Width must be 44 to 52 (Table B16.10) |
| 4 | Data_Width must be 128, 256 or 512 (Table B16.12) |
| 5 | Req_RSVDC_Width must be 0, 4, 8, 12, 16, 24 or 32 (Table B13.6) |
| 6 | Dat_RSVDC_Width must be 0, 4, 8, 12, 16, 24 or 32 (Table B13.9) |
| 7 | MPAM width must be 0, 12 or 15 (Table B13.6) |
| 8 | PBHA width must be 0 or 4 (Table B13.6) |
| 9 | MECID width must be 0 or 16 (Table B13.6) |
| 10 | StreamID width must be 0 or 16 (Table B13.6) |
| 11 | SecSID1 width must be 0 or 1 (Table B13.6) |
| 12 | max L-Credits per channel must be 1 to 15 (B14.2.1.1) |
| 13 | node_type must be one of RN-F, RN-D, RN-I, HN-F, HN-I, SN-F |

Rule 13 is listed for completeness; an unknown node type already raises in `__post_init__` during coercion.

## Derived Widths

| Property | Value | Spec |
|---|---|---|
| `snp_addr_width` (SAW) | RAW - 3 | B13.10.20: SNP Addr is Req Addr[RAW-1:3] |
| `mecid_or_streamid_width` | Max(E, R) | The REQ flit carries one slot for both |
| `data_check_width` / `poison_width` | DW/8 / DW/64, or 0 | B16.1.6 / B16.1.4 |
| `be_width`, `tag_width`, `tu_width` | DW/8, DW/32, DW/128 | Table B13.9 |

The flit totals, with N = NodeID_Width - 7:

| Channel | Formula | Table |
|---|---|---|
| REQ | 93 + RAW + Y + M + PB + S + Max(E, R) + 3N | B13.6 (TgtID, SrcID, ReturnNID grow) |
| RSP | 71 + 2N | B13.7 (TgtID, SrcID grow) |
| SNP | 53 + SAW + M + E + 2N | B13.8 (SrcID, FwdNID grow) |
| DAT | 240 / 389 / 687 (DW 128 / 256 / 512) + Y + DC + P + E + 3N | B13.9 (TgtID, SrcID, HomeNID grow) |

At the defaults (NodeID 7, RAW 44, DW 128) that is REQ 137, RSP 71, SNP 94, DAT 240, which are also the `chi_wires.sv` parameter defaults. `flit_width(channel)` returns one of them, `rtl_parameters()` the dict an RTL port in the RTLDesignSherpa style takes (`NODEID_WIDTH`, `ADDR_WIDTH`, ..., `REQ_FLIT_WIDTH`, ...). The unit tests check all four totals at the four corners of NodeID x RAW x DW against the numbers the tables print, and that each optional bus adds exactly its width.

## Flit Layouts

Four `Packet` subclasses, one per channel, each with a cached `FieldConfig` built per `CHIConfig`. Fields are added in table order with the first at bit 0, so the integer `pack()` returns is exactly `REQFLIT[(R-1):0]` on the wire. Width 0 means the field is absent (not in `field_names()`). The spec reuses a field's bits for another field in other message types; each such slot is one field here, named for its first-listed use, and the other names are **aliases** that read and write the same slot (`ALIASES[channel]`). Sub-fields inside a wider slot (DataPull = FwdState[0] in RSP, PBHA[3:0] in SNP FwdNID) are not aliased; set them by value.

### REQ (Table B13.6)

| Field | Width | Spec notes | Aliases |
|---|---|---|---|
| `qos` | 4 | QoS | |
| `tgtid` | NodeID | TgtID | |
| `srcid` | NodeID | SrcID | |
| `txnid` | 12 | TxnID | |
| `returnnid` | NodeID | ReturnNID / StashNID / {MBZ, DataTarget[6:0]} | `stashnid`, `datatarget` |
| `stashnidvalid` | 1 | StashNIDValid / Endian / Deep / PrefetchTgtHint | `endian`, `deep`, `prefetchtgthint` |
| `returntxnid` | 12 | ReturnTxnID / {6'b0, StashLPIDValid, StashLPID[4:0]} | `stashlpid` |
| `opcode` | 7 | Table B13.12 | |
| `multireq` | 1 | MultiReq | |
| `size` | 3 | Size (Table B13.17), or NumReq[2:0] when MultiReq = 1 | |
| `numreq_hi` | 3 | NumReq[5:3] when MultiReq = 1, else MBZ | |
| `addr` | RAW | Addr | |
| `pas` | 3 | PAS | |
| `likelyshared` | 1 | LikelyShared | |
| `allowretry` | 1 | AllowRetry | |
| `order` | 2 | Table B13.22 | |
| `pcrdtype` | 4 | PCrdType | |
| `memattr` | 4 | Table B13.18 | |
| `snpattr` | 1 | SnpAttr / DoDWT | `dodwt` |
| `lpid` | 8 | {3'b0, LPID[4:0]} / PGroupID / StashGroupID / TagGroupID | `pgroupid`, `stashgroupid`, `taggroupid` |
| `excl` | 1 | Excl / SnoopMe / CAH | `snoopme`, `cah` |
| `expcompack` | 1 | ExpCompAck | |
| `tagop` | 2 | TagOp | |
| `tracetag` | 1 | TraceTag | |
| `mpam` | M | MPAM | |
| `pbha` | PB | PBHA | |
| `mecid` | Max(E, R) | MECID / StreamID | `streamid` |
| `secsid1` | S | SecSID1 | |
| `rsvdc` | Y | RSVDC | |

### RSP (Table B13.7)

| Field | Width | Spec notes | Aliases |
|---|---|---|---|
| `qos` | 4 | QoS | |
| `tgtid` | NodeID | TgtID | |
| `srcid` | NodeID | SrcID | |
| `txnid` | 12 | TxnID (the DBID in CompAck, B2.4.3) | |
| `opcode` | 5 | Table B13.14 | |
| `resperr` | 2 | Table B13.33 | |
| `resp` | 3 | Tables B13.34 / B13.35 | |
| `fwdstate` | 3 | FwdState[2:0] / {2'b0, DataPull} | `datapull` |
| `cbusy` | 3 | CBusy | |
| `dbid` | 12 | DBID / {4'b0, PGroupID} / StashGroupID / TagGroupID | `pgroupid`, `stashgroupid`, `taggroupid` |
| `pcrdtype` | 4 | PCrdType | |
| `tagop` | 2 | TagOp | |
| `tracetag` | 1 | TraceTag | |
| `cachelineid` | 6 | CacheLineID | |

### SNP (Table B13.8)

| Field | Width | Spec notes | Aliases |
|---|---|---|---|
| `qos` | 4 | QoS | |
| `srcid` | NodeID | SrcID | |
| `txnid` | 12 | TxnID | |
| `fwdnid` | NodeID | FwdNID / {MBZ, PBHA[3:0]} | `pbha` |
| `fwdtxnid` | 12 | FwdTxnID / StashLPID group / {4'b0, VMIDExt} | `stashlpid`, `vmidext` |
| `opcode` | 5 | Table B13.15 | |
| `addr` | SAW | Addr[RAW-1:3]; `byte_addr` is `addr << 3` | |
| `pas` | 3 | PAS | |
| `donotgotosd` | 1 | DoNotGoToSD | |
| `rettosrc` | 1 | RetToSrc | |
| `tracetag` | 1 | TraceTag | |
| `mpam` | M | MPAM | |
| `mecid` | E | MECID | |

### DAT (Table B13.9)

| Field | Width | Spec notes | Aliases |
|---|---|---|---|
| `qos` | 4 | QoS | |
| `tgtid` | NodeID | TgtID | |
| `srcid` | NodeID | SrcID | |
| `txnid` | 12 | TxnID (the DBID in write data, B2.4.3) | |
| `homenid` | NodeID | HomeNID / {MBZ, MismatchedMECID, PBHA[3:0]} | `pbha`, `mismatchedmecid` |
| `opcode` | 4 | Table B13.16 | |
| `resperr` | 2 | Table B13.33 | |
| `resp` | 3 | Tables B13.34 / B13.35 | |
| `datasource` | 8 | DataSource[7:0] / {5'b0, FwdState[2:0]} | `fwdstate` |
| `datapull` | 1 | DataPull | |
| `cbusy` | 3 | CBusy | |
| `mecid` | E | MECID | |
| `dbid` | 16 | {4'b0, DBID[11:0]} | |
| `ccid` | 2 | CCID | |
| `dataid` | 2 | DataID (Table B13.39) | |
| `cachelineid` | 6 | CacheLineID | |
| `tagop` | 2 | TagOp | |
| `tag` | DW/32 | Tag | |
| `tu` | DW/128 | TU | |
| `tracetag` | 1 | TraceTag | |
| `cah` | 1 | CAH | |
| `numdat` | 2 | NumDat | |
| `replicate` | 1 | Replicate | |
| `rsvdc` | Y | RSVDC | |
| `be` | DW/8 | BE | |
| `data` | DW | Data; `data_bytes()` / `set_data_bytes()` are little-endian, byte n = Data[8n+7:8n] | |
| `datacheck` | DC | DataCheck | |
| `poison` | P | Poison | |

`tests/unit/test_chi_flits.py` walks each table from bit 0 and asserts the positions (REQ `addr` at [107:64] at the defaults, RSP `dbid` at [75:64] at NodeID 16, SNP `addr` at [87:47] at RAW 44, DAT `data` at [239:112] at DW 128), round-trips random words on every channel at the defaults and at a wide configuration (NodeID 16, RAW 52, DW 512, every optional bus on), and checks that an alias reads and writes its slot.

## Pack and Unpack

```python
cfg = CHIConfig()
f = CHIReqFlit(cfg, tgtid=0, srcid=1, txnid=5, opcode=ReqOpcode.ReadShared,
               size=Size.B64, addr=0x1000, expcompack=1, memattr=MemAttr.CACHEABLE | MemAttr.ALLOCATE)
word = f.pack()                                  # the REQFLIT bus value
g = CHIReqFlit.from_word(cfg, word)              # == CHIReqFlit(cfg).unpack(word)
assert g.opcode_name == 'ReadShared' and g.width == cfg.req_flit_width
```

`pack()` places every field at its declared `bit_position`, which is the wire layout a spec describes. That is the **only** packer to use for a CHI flit: `Packet.pack_for_fifo()` is a per-field dict, and the combined-signal packer in `data_strategies` walks `field_names()` from bit 0 and so inverts the declared layout (the note on `Packet.pack` says so and points here). `CHIPort` and `CHIMonitor` use `pack()` and `from_word()` and nothing else.

`is_lcrd_return` is true for opcode 0 on any channel (B13.11: a Link flit has opcode 0 and TxnID 0; the port builds one with `flit_class(ch)(cfg, opcode=0, txnid=0)`). `opcode_name` decodes per channel and returns `?0xNN` for a value the tables do not name. `__repr__` prints the opcode name, the IDs and the fields a reader wants per channel (addr and size for REQ, the byte address for SNP, resp / err / dbid for RSP and DAT, plus dataid for DAT).

## Opcodes

Four `IntEnum`s transcribed from B13.10 with every reserved value left out, so `ReqOpcode(0x06)` raises: a BFM must not encode what the spec does not name.

| Enum | Table | Width | Notes |
|---|---|---|---|
| `ReqOpcode` | B13.12 | 7 | Opcode[6] = 1 column values are `0x40 \| low`; `ReqLCrdReturn` = 0 |
| `AtomicOp`, `atomic_opcode(base, op)` | B13.13 | 3 | ADD CLR EOR SET SMAX SMIN UMAX UMIN as Opcode[2:0] of AtomicStore (0x28) / AtomicLoad (0x30); `req_opcode_name(0x2A)` is `AtomicStore.EOR` |
| `RspOpcode` | B13.14 | 5 | 0x1C-0x1F (C2C) left out |
| `SnpOpcode` | B13.15 | 5 | Includes the Fwd and Stash snoops by name; only the non-forwarding set is modelled |
| `DatOpcode` | B13.16 | 4 | 0xD (C2C) left out |

`opcode_name(channel, value)` is the per-channel decoder the flits use.

## Field Encodings

| Encoding | Table | Values |
|---|---|---|
| `Size` | B13.17 | B1..B64 = 0..6, bytes = `1 << Size`; `.nbytes`; `Size.of(n)` for a power of two 1..64, raises otherwise; 0b111 reserved |
| `MemAttr` | B13.18 | Bit positions to OR: EWA = 1, DEVICE = 2, CACHEABLE = 4, ALLOCATE = 8 |
| `Order` | B13.22 | NONE 00, REQ_ACCEPTED 01 (HN to SN only), REQ_ORDER_OWO 10 (Request Order, or OWO when ExpCompAck = 1), ENDPOINT 11 |
| `RespErr` | B13.33 | OK 00, EXOK 01, DERR 10, NDERR 11 |
| `FwdState` | B13.37 | I 000, SC 001, UC 010, UD_PD 110, SD_PD 111 (an encoding only; DCT is not modelled) |

### Resp per message class (Table B13.35)

The same Resp[2:0] encoding reads differently per message class, so decode with `resp_state(kind, resp)` rather than the `Resp` enum name; it raises for an encoding reserved in that class. `resp_encode(state)` is the inverse for a state name.

| Resp[2:0] | `'snoop'` (SnpResp*) | `'comp'` (Comp, CompData, DataSepResp) | `'writedata'` | `'compack'` |
|---|---|---|---|---|
| 000 | I | I | I | I |
| 001 | SC | SC | SC | SC |
| 010 | UC (also SnpResp_UD / SnpRespData_UD, Tables B4.31 / B4.33) | UC | UC | UC |
| 011 | SD | reserved | reserved | reserved |
| 100 | I_PD | reserved | reserved | reserved |
| 101 | SC_PD | reserved | reserved | reserved |
| 110 | UC_PD | UD_PD | UD_PD | UD_PD |
| 111 | reserved | SD_PD | SD_PD | SD_PD |

The cache states themselves are plain strings, `I`, `UC`, `UCE`, `UD`, `UDP`, `SC`, `SD` (B4.1), with `CACHE_STATES`, `UNIQUE_STATES` (UC, UCE, UD, UDP) and `DIRTY_STATES` (UD, UDP, SD) as the vocabulary.

### DataID arithmetic (B2.9.4, Table B2.16)

A data response or write is one packet per DW-wide window of the 64-byte line, each named by DataID:

| Function | Result |
|---|---|
| `data_id(addr, dw)` | DW 128: `addr[5:4]`; DW 256: `{addr[5], 0}` (0 or 2); DW 512: 0 |
| `data_ids_for(nbytes, addr, dw)` | One DataID when `nbytes <= dw/8`, else the DataIDs of each dw/8-byte step across the size-aligned window, in address order: 64 B on DW 128 is `[0, 1, 2, 3]`, on 256 `[0, 2]`, on 512 `[0]`; 16 B at 0x30 on DW 128 is `[3]` |
| `data_window_lo(line, did, dw)` | Byte address of the first byte of the window DataID `did` names |
| `data_windows(addr, nbytes, dw)` | `[(DataID, window_lo)]` for a transfer, the form the BFMs chunk with |

Bytes sit at their natural positions inside the window and BE marks the ones the transfer covers; `CHITransaction.write_chunks()` and `read_data()` on the protocol page apply the same arithmetic in both directions.

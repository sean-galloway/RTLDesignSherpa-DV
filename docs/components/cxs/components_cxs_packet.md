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

# CXS Configuration, Control Word and Packing

## CXSConfig

A frozen dataclass, one per interface; `with_(**changes)` returns a modified copy.

| Field | Spec property | Default |
|---|---|---|
| `issue` | (issue; `CXSIssue`, int 1-4 or 'A'-'D') | D |
| `data_width` | CXSDATAFLITWIDTH | 256 |
| `max_pkt_per_flit` | CXSMAXPKTPERFLIT (1 = CXS-Lite) | 2 |
| `start_align` | CXS_START_ALIGNMENT | 16 |
| `has_last` / `has_prcltype` | CXS_LAST / CXS_PROTOCOL_TYPE | False |
| `srcid_width` / `tgtid_width` / `user_width` | CXS_SRCID_WIDTH / CXS_TGTID_WIDTH / CXS_USER_WIDTH | 0 |
| `max_credit` | CXS_MAX_CREDIT | 15 |
| `link_control` | CXSLINKCONTROL = Explicit_Credit_Return | True |
| `check` | CXSCHECKTYPE = Odd_Byte_Parity | False |
| `continuous` | CXSCONTINUOUSDATA | False |

Derived: `cntl_width`, `cntl_fields()` (the rows of IHI 0079D Table 4-5 or 4-7), `check_widths()` (Table 3-2), `is_compatible_rx(rx)` (Table 2-3), and `rtl_parameters()` (the `cxs_master`/`cxs_slave` parameter dict). `tests/unit/test_cxs_config.py` checks `cntl_width` and the END field position against every row of both tables.

## CXSCntl

```python
c = CXSCntl(starts=(0, 1), ends=(2, 7))       # pointers in spec units
word = c.encode(cfg)
CXSCntl.decode(cfg, word).violations(cfg, open_before=False)  # [] when legal
```

Start pointers are in alignment units (16 or 4 bytes). End pointers are in 4-byte units and point at the last aligned 4 bytes of the packet. `violations()` reports non-thermometer START/END, ENDERROR without END, non-increasing pointers, a packet ending that never started, too many packets in a flit, overlap, and (with 16-byte alignment) a start that is not the first free boundary.

## Packing

`CXSPacketizer(cfg).add_all(packets).flush()` returns flits. It follows 4.1:

- A packet starts at the first free alignment boundary and fills every following byte until it ends or the flit ends.
- A packet that runs past the flit continues at byte 0 of the next flit.
- At most CXSMAXPKTPERFLIT packets have bytes in one flit, and all of them share one stream (protocol type, source ID, target ID).
- CXSLAST is low while a packet is open, and after a packet with `keep_with_next`.
- With 4-byte alignment, an optional `gap_hook` inserts the legal 4-byte gaps.

A stream field the interface has no wire for (for example `prcltype=1` with `has_prcltype=False`) raises, because it would be dropped silently. `CXSDepacketizer` reverses the packing and records every rule a received flit breaks. `tests/unit/test_cxs_packet.py` reproduces the IHI 0079B Table 4-3 example exactly and round-trips random traffic for every issue.

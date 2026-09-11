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

# wb4_packet.py

`WB4Packet(Packet)`: one Wishbone transfer, request and termination together.

| Field | Bits | Driven by | Meaning |
|---|---|---|---|
| `we` | 1 | master | 0 read, 1 write |
| `adr` | addr_width | master | byte address |
| `dat_w` | data_width | master | write data (`DAT_O` at the master) |
| `sel` | data_width/8 | master | byte select; default all ones |
| `cti` | 3 | master | burst hint: 0 CLASSIC, 1 CONST, 2 INCR, 7 EOB |
| `bte` | 2 | master | burst type: 0 LINEAR, 1 WRAP4, 2 WRAP8, 3 WRAP16 |
| `dat_r` | data_width | slave | read data (`DAT_I` at the master) |
| `status` | 2 | slave | 0 ACK, 1 ERR, 2 RTY |

`cti` and `bte` are the registered-feedback burst hints of B4 chapter 4.
They are advisory: nothing in the framework acts on one, and no block in the
RTL library does either -- what a burst means belongs to the peripheral. Both
put the non-burst case at zero, so a packet built for a bus with no hint
wires compares equal to one sampled off that bus, and every testbench written
before the hints existed still pairs its packets the same way.

Metadata outside the fields: `count` (ordinal at the component that built
it), `start_time` (request presented), `end_time` (terminated); all three are
skipped by `==`. Properties: `direction` (`'READ'`/`'WRITE'`), `status_name`,
`cti_name`, `bte_name`, and `in_burst` (the hint is not CLASSIC).
`formatted(compact=True)` gives one line, naming the hints only when a
transfer actually carries one:

```
WB WRITE adr=0x00001234 sel=0b1111 dat_w=0xDEADBEEF ACK
WB READ  adr=0x00001238 sel=0b1111 dat_r=0x0000002A EOB/WRAP8 ACK
```

`WB4Packet.create_wb4_field_config(addr_width, data_width, sel_width)` is the
`FieldConfig` the BFMs use; pass your own to the constructor to add fields.

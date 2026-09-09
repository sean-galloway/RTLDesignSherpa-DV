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
| `dat_r` | data_width | slave | read data (`DAT_I` at the master) |
| `status` | 2 | slave | 0 ACK, 1 ERR, 2 RTY |

Metadata outside the fields: `count` (ordinal at the component that built
it), `start_time` (request presented), `end_time` (terminated); all three are
skipped by `==`. Properties: `direction` (`'READ'`/`'WRITE'`), `status_name`.
`formatted(compact=True)` gives one line:

```
WB WRITE adr=0x00001234 sel=0b1111 dat_w=0xDEADBEEF ACK
```

`WB4Packet.create_wb4_field_config(addr_width, data_width, sel_width)` is the
`FieldConfig` the BFMs use; pass your own to the constructor to add fields.

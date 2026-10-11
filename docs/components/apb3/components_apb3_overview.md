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

# APB3 Components Overview

APB3 is implemented as a subclass of the APB4 BFMs. It exposes the same base signal set, but only `PSLVERR` is optional; `PPROT` and `PSTRB` are not part of the APB3 signal set and are not bound.

## Components

- **APB3Master** — drives APB3 transfers. Raises if a caller passes `strb` or `pprot`.
- **APB3Slave** — memory-backed responder. Inherits the unified APB4 slave state machine.
- **APB3Monitor** — passive observer that builds `APB3Packet` objects.
- **APB3Packet** — packet class with the APB3 field set (`pwrite`, `paddr`, `pwdata`, `prdata`, `pslverr`).

## Factory Functions

```python
from CocoTBFramework.components.apb3 import (
    create_apb3_master,
    create_apb3_slave,
    create_apb3_monitor,
)

master = create_apb3_master(dut, "APB3_Master", "apb_", dut.clk)
slave = create_apb3_slave(dut, "APB3_Slave", "apb_", dut.clk, registers=1024)
monitor = create_apb3_monitor(dut, "APB3_Monitor", "apb_", dut.clk)
```

## Packet Construction

```python
from CocoTBFramework.components.apb3 import APB3Packet

write_pkt = APB3Packet(pwrite=1, paddr=0x100, pwdata=0xAB)
read_pkt = APB3Packet(pwrite=0, paddr=0x100)
```

`PSTRB` and `PPROT` kwargs are ignored if accidentally passed.

## Signal Set

| Signal | Direction (master) | Optional in APB3 |
|--------|--------------------|------------------|
| PSEL   | out                | no               |
| PENABLE| out                | no               |
| PWRITE | out                | no               |
| PADDR  | out                | no               |
| PWDATA | out                | no               |
| PRDATA | in                 | no               |
| PREADY | in                 | no               |
| PSLVERR| in                 | yes              |

APB3 lives in `src/CocoTBFramework/components/apb3/` and is tracked as issue #87.

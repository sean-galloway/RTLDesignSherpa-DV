"""Generic, TOML-driven testbench for the concurrent-stress bridges.

Parses a bridge's TOML configuration at construction time, auto-builds
the appropriate BFM topology (AXI4 / AXIL4 / APB), pre-seeds each slave's
MemoryModel with a misroute-detection pattern, and provides high-level
concurrency-stress helpers designed to exercise the framework's BFM
synchronization paths:

- ``parallel_storm`` — every master fires N concurrent bursts at once;
  exercises per-ID response pickup (v0.1.1 #3), AW+W serialization
  (v0.1.1 #4), and `completion_locks` (v0.1.1 #5).

- ``same_id_storm`` — N transactions to the same slave with the same AXI4
  ID from the same master; concentrates load on the per-ID lock paths.

- ``cross_protocol_race`` — AXI4 + AXIL + APB masters all issue at the
  same simulation time; exercises the APBMaster queued pipeline that
  APB5Master inherited in #15.

- ``read_response_race`` — many concurrent reads with overlapping IDs;
  the response-pickup demux (v0.1.1 #3) is the hot path.

For each bridge config in ``tests/sim/bridge_specs/``, instantiate
``ConcurrentBridgeTB(dut, toml_path=...)`` and drive the helpers from
``@cocotb.test`` functions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# tomllib is stdlib on 3.11+; tomli is the backport
try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from TBClasses.shared.tbbase import TBBase

# Protocol BFMs — same import surface as the existing RDS Bridge TBs
from CocoTBFramework.components.axi4.axi4_interfaces import (
    AXI4MasterRead,
    AXI4MasterWrite,
    AXI4SlaveRead,
    AXI4SlaveWrite,
)
from CocoTBFramework.components.axil4.axil4_interfaces import (
    AXIL4MasterRead,
    AXIL4MasterWrite,
    AXIL4SlaveRead,
    AXIL4SlaveWrite,
)
from CocoTBFramework.components.apb.apb_components import APBMaster, APBSlave
from CocoTBFramework.components.shared.memory_model import MemoryModel

from .scoreboard import ConcurrentBridgeScoreboard


class ConcurrentBridgeTB(TBBase):
    """Generic concurrent-stress TB for any bridge with a TOML spec.

    Args:
        dut: cocotb DUT handle (a generated bridge_* module).
        toml_path: Path to the TOML file describing the bridge. Either a
            ``Path``, a string, or ``None`` (autodetect via DUT name).
    """

    # ---------- class-level constants ----------

    # Per-slave MemoryModel cap. Slaves with huge addr_ranges (GB-class
    # DDR) would OOM the test harness if we eagerly allocated the full
    # window. Tests address inside this cap by convention.
    SLAVE_MEM_CAP_BYTES = 16 * 1024  # 16 KB per slave is plenty for stress tests

    # Address-decode page granularity (same as bridge generator validator)
    PAGE_SIZE = 0x1000

    def __init__(self, dut, toml_path: Optional[str] = None):
        super().__init__(dut)
        self.dut = dut
        self.clock = dut.aclk
        self.clock_name = "aclk"
        self.reset_n = dut.aresetn

        # ---- Load and parse the bridge TOML ----
        self._toml_path = self._resolve_toml_path(toml_path)
        with open(self._toml_path, "rb") as f:
            self._cfg = tomllib.load(f)

        self.bridge_name: str = self._cfg["bridge"]["name"]
        self.log.info(f"ConcurrentBridgeTB: configuring for {self.bridge_name}")

        # ---- Indexed master/slave descriptors ----
        # Each element: dict with name, prefix, protocol, channels, widths,
        # plus (for slaves) base_addr / addr_range.
        self.master_descs: List[Dict[str, Any]] = self._cfg["bridge"].get("masters", [])
        self.slave_descs: List[Dict[str, Any]] = self._cfg["bridge"].get("slaves", [])
        self.num_masters = len(self.master_descs)
        self.num_slaves = len(self.slave_descs)

        # ---- BFM containers, indexed by master/slave index ----
        # AXI4/AXIL: separate read+write handles. APB: single handle.
        self.master_rd: Dict[int, Any] = {}
        self.master_wr: Dict[int, Any] = {}
        self.master_apb: Dict[int, Any] = {}
        self.slave_rd: Dict[int, Any] = {}
        self.slave_wr: Dict[int, Any] = {}
        self.slave_apb: Dict[int, Any] = {}
        self.slave_memory: Dict[int, MemoryModel] = {}

        # ---- Scoreboard ----
        self.sb = ConcurrentBridgeScoreboard(self.log)

        # ---- Build all BFMs ----
        for slave_idx, sdesc in enumerate(self.slave_descs):
            self._setup_slave(slave_idx, sdesc)
        for master_idx, mdesc in enumerate(self.master_descs):
            self._setup_master(master_idx, mdesc)

        # ---- Connectivity ----
        self._connectivity = self._parse_connectivity()

        self.log.info(
            f"ConcurrentBridgeTB ready: {self.num_masters} masters, "
            f"{self.num_slaves} slaves, "
            f"{sum(sum(row) for row in self._connectivity)} active paths"
        )

    # ---------- TOML / config helpers ----------

    def _resolve_toml_path(self, hint: Optional[str]) -> Path:
        if hint is not None:
            return Path(hint)
        # Autodetect: bridge_specs/<bridge_name>.toml relative to this file.
        here = Path(__file__).resolve()
        specs_dir = here.parent.parent.parent / "bridge_specs"
        dut_name = getattr(self.dut, "_name", None) or str(self.dut)
        candidate = specs_dir / f"{dut_name}.toml"
        if candidate.exists():
            return candidate
        raise FileNotFoundError(
            f"Could not auto-locate bridge TOML; tried {candidate}. "
            "Pass toml_path= explicitly."
        )

    def _parse_connectivity(self) -> List[List[int]]:
        """Read the per-bridge connectivity CSV that sits alongside the TOML."""
        csv_path = self._toml_path.parent / f"{self.bridge_name}_connectivity.csv"
        if not csv_path.exists():
            # Default: full connectivity
            return [[1] * self.num_slaves for _ in range(self.num_masters)]
        with open(csv_path) as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        # First line is header: master\slave,slave0,slave1,...
        matrix: List[List[int]] = []
        for ln in lines[1:]:
            cells = ln.split(",")
            # cells[0] is master name; rest are 0/1
            matrix.append([int(c) for c in cells[1:]])
        return matrix

    @staticmethod
    def _parse_addr(s) -> int:
        """Accept int or '0x...' string."""
        if isinstance(s, int):
            return s
        return int(str(s), 0)

    @staticmethod
    def _strip_prefix(prefix: str) -> str:
        """BFMs handle the underscore separator themselves; strip trailing _."""
        return prefix.rstrip("_")

    # ---------- BFM construction (protocol-dispatched) ----------

    def _setup_master(self, master_idx: int, desc: Dict[str, Any]) -> None:
        proto = desc.get("protocol", "axi4")
        channels = desc.get("channels", "rw")
        prefix = self._strip_prefix(desc["prefix"])
        name = desc["name"]
        dw = desc["data_width"]
        aw = desc.get("addr_width", 32)
        idw = desc.get("id_width", 0)
        uw = desc.get("user_width", 1)
        self.log.debug(
            f"  master[{master_idx}] {name}: proto={proto} ch={channels} "
            f"prefix={prefix} dw={dw} idw={idw}"
        )

        if proto == "axi4":
            if "r" in channels:
                self.master_rd[master_idx] = AXI4MasterRead(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw,
                    id_width=idw or 4, user_width=uw,
                    multi_sig=True,
                )
            if "w" in channels:
                self.master_wr[master_idx] = AXI4MasterWrite(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw,
                    id_width=idw or 4, user_width=uw,
                    multi_sig=True,
                )
        elif proto == "axil":
            if "r" in channels:
                self.master_rd[master_idx] = AXIL4MasterRead(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw, user_width=uw,
                    multi_sig=True,
                )
            if "w" in channels:
                self.master_wr[master_idx] = AXIL4MasterWrite(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw, user_width=uw,
                    multi_sig=True,
                )
        elif proto == "apb":
            self.master_apb[master_idx] = APBMaster(
                self.dut, f"M{master_idx}_{name}", prefix, self.clock,
                bus_width=dw, addr_width=aw, log=self.log,
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown master protocol {proto!r}")

    def _setup_slave(self, slave_idx: int, desc: Dict[str, Any]) -> None:
        proto = desc.get("protocol", "axi4")
        channels = desc.get("channels", "rw")
        prefix = self._strip_prefix(desc["prefix"])
        name = desc["name"]
        dw = desc["data_width"]
        aw = desc.get("addr_width", 32)
        idw = desc.get("id_width", 0)
        uw = desc.get("user_width", 1)
        base = self._parse_addr(desc["base_addr"])
        addr_range = self._parse_addr(desc["addr_range"])
        self.log.debug(
            f"  slave[{slave_idx}] {name}: proto={proto} ch={channels} "
            f"prefix={prefix} dw={dw} base=0x{base:08x} range=0x{addr_range:x}"
        )

        # Pre-seeded MemoryModel — capped at SLAVE_MEM_CAP_BYTES
        bytes_per_word = dw // 8
        mem_bytes = min(addr_range, self.SLAVE_MEM_CAP_BYTES)
        preset = self._build_preset(slave_idx, mem_bytes, dw)
        self.slave_memory[slave_idx] = MemoryModel(
            num_lines=mem_bytes // bytes_per_word,
            bytes_per_line=bytes_per_word,
            preset_values=list(preset),
            log=self.log,
        )

        if proto == "axi4":
            if "r" in channels:
                self.slave_rd[slave_idx] = AXI4SlaveRead(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw,
                    id_width=idw or 4, user_width=uw,
                    multi_sig=True,
                    memory_model=self.slave_memory[slave_idx],
                    base_addr=base,
                )
            if "w" in channels:
                self.slave_wr[slave_idx] = AXI4SlaveWrite(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw,
                    id_width=idw or 4, user_width=uw,
                    multi_sig=True,
                    memory_model=self.slave_memory[slave_idx],
                    base_addr=base,
                )
        elif proto == "axil":
            if "r" in channels:
                self.slave_rd[slave_idx] = AXIL4SlaveRead(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw, user_width=uw,
                    multi_sig=True,
                    memory_model=self.slave_memory[slave_idx],
                    base_addr=base,
                )
            if "w" in channels:
                self.slave_wr[slave_idx] = AXIL4SlaveWrite(
                    self.dut, self.clock,
                    prefix=prefix, log=self.log,
                    data_width=dw, addr_width=aw, user_width=uw,
                    multi_sig=True,
                    memory_model=self.slave_memory[slave_idx],
                    base_addr=base,
                )
        elif proto == "apb":
            # APBSlave manages its own memory — we pass the preseed via
            # registers= and then swap in our shared MemoryModel for
            # cross-protocol scoreboard consistency.
            self.slave_apb[slave_idx] = APBSlave(
                self.dut, f"S{slave_idx}_{name}", prefix, self.clock,
                registers=list(preset),
                bus_width=dw, addr_width=aw,
                log=self.log,
            )
            self.slave_apb[slave_idx].mem = self.slave_memory[slave_idx]
        else:  # pragma: no cover
            raise ValueError(f"Unknown slave protocol {proto!r}")

    # ---------- Seed pattern (misroute detection) ----------

    @staticmethod
    def _seed_value(slave_idx: int, word_offset: int, data_width: int) -> int:
        """Deterministic per-slave seed: upper byte = (slave_idx+1), low
        bits = word index. A misrouted write/read shows up at a glance:
        a read of slave 4 returning 0x02_xxxxxx came from slave 1.
        """
        id_byte = (slave_idx + 1) & 0xFF
        index_mask = (1 << (data_width - 8)) - 1
        return (id_byte << (data_width - 8)) | (word_offset & index_mask)

    def _build_preset(self, slave_idx: int, mem_bytes: int, data_width: int) -> bytearray:
        bpw = data_width // 8
        num_words = mem_bytes // bpw
        buf = bytearray(mem_bytes)
        for w in range(num_words):
            v = self._seed_value(slave_idx, w, data_width)
            buf[w * bpw:(w + 1) * bpw] = v.to_bytes(bpw, "little")
        return buf

    def expected_seed_at(self, slave_idx: int, address: int,
                          byte_count: int = 4) -> int:
        """Return the seeded value at ``address`` for the given slave."""
        sdesc = self.slave_descs[slave_idx]
        base = self._parse_addr(sdesc["base_addr"])
        offset = address - base
        if offset < 0 or offset >= self.SLAVE_MEM_CAP_BYTES:
            # Outside the seeded region — value is 0 (raw allocation)
            return 0
        dw = sdesc["data_width"]
        bpw = dw // 8
        word_offset = offset // bpw
        word_val = self._seed_value(slave_idx, word_offset, dw)
        # Pick out the byte_count low bytes at the right within-word offset
        intra_word = offset % bpw
        word_bytes = word_val.to_bytes(bpw, "little")
        return int.from_bytes(
            word_bytes[intra_word:intra_word + byte_count], "little"
        )

    def slave_mem_read(
        self, slave_idx: int, address: int, byte_count: int = 4
    ) -> int:
        """Read back ``byte_count`` bytes from slave's MemoryModel as int."""
        sdesc = self.slave_descs[slave_idx]
        base = self._parse_addr(sdesc["base_addr"])
        offset = address - base
        mem = self.slave_memory[slave_idx]
        return int.from_bytes(bytes(mem.read(offset, byte_count)), "little")

    # ---------- Bridge routing helpers ----------

    def slave_for_address(self, address: int) -> Optional[int]:
        """Which slave_idx (if any) owns this address?"""
        for idx, sdesc in enumerate(self.slave_descs):
            base = self._parse_addr(sdesc["base_addr"])
            rng = self._parse_addr(sdesc["addr_range"])
            if base <= address < base + rng:
                return idx
        return None

    def in_window(self, slave_idx: int, address: int) -> bool:
        return self.slave_for_address(address) == slave_idx

    def can_route(self, master_idx: int, slave_idx: int) -> bool:
        """Honor the connectivity matrix from the bridge CSV."""
        return bool(self._connectivity[master_idx][slave_idx])

    # ---------- Clock / reset ----------

    async def setup_clocks_and_reset(self) -> None:
        await self.start_clock(self.clock_name, 10, "ns")
        await self.assert_reset()
        await ClockCycles(self.clock, 8)
        await self.deassert_reset()
        await ClockCycles(self.clock, 8)

    async def assert_reset(self) -> None:
        self.reset_n.value = 0

    async def deassert_reset(self) -> None:
        self.reset_n.value = 1

    # ---------- Single-transaction helpers (protocol-dispatched) ----------

    async def master_write(
        self,
        master_idx: int,
        address: int,
        data: int,
        byte_count: int = 4,
        txn_id: Optional[int] = None,
        register_with_sb: bool = True,
    ) -> None:
        proto = self.master_descs[master_idx].get("protocol", "axi4")
        slave_idx = self.slave_for_address(address)

        if proto == "axi4":
            wr = self.master_wr[master_idx]
            kwargs = {"id": txn_id} if txn_id is not None else {}
            await wr.write_transaction(address, [data], **kwargs)
        elif proto == "axil":
            wr = self.master_wr[master_idx]
            await wr.write_transaction(address, [data])
        elif proto == "apb":
            await self.master_apb[master_idx].write(address, data)
        else:  # pragma: no cover
            raise ValueError(f"Unknown master protocol {proto!r}")

        if register_with_sb and slave_idx is not None:
            self.sb.register_write(
                master_idx, slave_idx, address, data, byte_count, txn_id
            )

    async def master_read(
        self,
        master_idx: int,
        address: int,
        byte_count: int = 4,
        txn_id: Optional[int] = None,
        register_with_sb: bool = True,
    ) -> int:
        proto = self.master_descs[master_idx].get("protocol", "axi4")
        slave_idx = self.slave_for_address(address)

        if proto == "axi4":
            rd = self.master_rd[master_idx]
            kwargs = {"id": txn_id} if txn_id is not None else {}
            result = await rd.read_transaction(address, **kwargs)
            value = result[0] if isinstance(result, list) else result
        elif proto == "axil":
            rd = self.master_rd[master_idx]
            result = await rd.read_transaction(address)
            value = result[0] if isinstance(result, list) else result
        elif proto == "apb":
            txn = await self.master_apb[master_idx].read(address)
            value = txn.fields.get("prdata", 0)
        else:  # pragma: no cover
            raise ValueError(f"Unknown master protocol {proto!r}")

        if register_with_sb and slave_idx is not None:
            expected = self.expected_seed_at(slave_idx, address, byte_count)
            self.sb.register_read(
                master_idx, slave_idx, address, expected, byte_count, txn_id
            )
            err = self.sb.record_read_response(master_idx, txn_id, value)
            if err:
                self.log.error(f"scoreboard: {err}")
        return value

    # ---------- Concurrency stress helpers ----------

    async def parallel_storm(
        self,
        per_master_txns: int = 16,
        write_fraction: float = 0.5,
    ) -> None:
        """Every master fires ``per_master_txns`` transactions concurrently
        via ``cocotb.start_soon``. Each transaction targets a random
        reachable slave (per the connectivity matrix). Random mix of
        read and write per ``write_fraction``.

        Exercises:
          - Per-ID response pickup (v0.1.1 #3)
          - AW+W serialization (v0.1.1 #4)
          - `completion_locks` (v0.1.1 #5)
          - APBSlave unified state machine under concurrent fan-in (#15 Phase B)
        """
        import random
        rng = random.Random(0xC0DECAFE)  # arbitrary deterministic seed

        tasks = []
        for m_idx in range(self.num_masters):
            reachable = [
                s for s in range(self.num_slaves) if self.can_route(m_idx, s)
            ]
            if not reachable:
                continue
            for n in range(per_master_txns):
                s_idx = rng.choice(reachable)
                base = self._parse_addr(self.slave_descs[s_idx]["base_addr"])
                bpw = self.master_descs[m_idx]["data_width"] // 8
                # Address inside the seeded cap, aligned to master width
                offset = (rng.randint(0, self.SLAVE_MEM_CAP_BYTES // bpw - 1)
                          * bpw)
                addr = base + offset
                txn_id = n % (1 << (self.master_descs[m_idx].get("id_width") or 4))
                if rng.random() < write_fraction:
                    data = 0xDE000000 | (m_idx << 20) | (s_idx << 16) | (n & 0xFFFF)
                    tasks.append(cocotb.start_soon(
                        self.master_write(m_idx, addr, data, bpw, txn_id)
                    ))
                else:
                    tasks.append(cocotb.start_soon(
                        self.master_read(m_idx, addr, bpw, txn_id)
                    ))

        for t in tasks:
            await t.join()

    async def same_id_storm(
        self,
        master_idx: int,
        slave_idx: int,
        txn_id: int,
        count: int = 16,
        operation: str = "write",
    ) -> None:
        """Dispatch ``count`` concurrent transactions to the same slave
        with the same AXI4 ID from the same master. Concentrates load on
        the per-ID completion locks and the AW+W serialization lock.
        """
        base = self._parse_addr(self.slave_descs[slave_idx]["base_addr"])
        bpw = self.master_descs[master_idx]["data_width"] // 8

        tasks = []
        for n in range(count):
            addr = base + (n * bpw)
            if operation == "write":
                data = 0xC0000000 | (master_idx << 20) | (txn_id << 8) | (n & 0xFF)
                tasks.append(cocotb.start_soon(
                    self.master_write(master_idx, addr, data, bpw, txn_id)
                ))
            else:
                tasks.append(cocotb.start_soon(
                    self.master_read(master_idx, addr, bpw, txn_id)
                ))
        for t in tasks:
            await t.join()

    async def cross_protocol_race(
        self, per_master_txns: int = 4
    ) -> None:
        """Issue concurrently from every master with a different protocol,
        each hitting any slave it can reach. Forces the scheduler to mix
        AXI4 / AXIL / APB driver loops in the same simulation cycle window.
        """
        import random
        rng = random.Random(0xCAFEFACE)

        # Group masters by protocol to ensure the race actually happens
        by_proto: Dict[str, List[int]] = {}
        for idx, mdesc in enumerate(self.master_descs):
            by_proto.setdefault(mdesc.get("protocol", "axi4"), []).append(idx)

        if len(by_proto) < 2:
            self.log.info(
                "cross_protocol_race: only one master protocol in this bridge; "
                "falling back to parallel_storm"
            )
            await self.parallel_storm(per_master_txns, write_fraction=0.5)
            return

        tasks = []
        for proto, masters in by_proto.items():
            for m_idx in masters:
                reachable = [
                    s for s in range(self.num_slaves) if self.can_route(m_idx, s)
                ]
                if not reachable:
                    continue
                for n in range(per_master_txns):
                    s_idx = rng.choice(reachable)
                    base = self._parse_addr(self.slave_descs[s_idx]["base_addr"])
                    bpw = self.master_descs[m_idx]["data_width"] // 8
                    addr = base + (n * bpw)
                    data = 0xCC000000 | (m_idx << 20) | (s_idx << 16) | n
                    txn_id = n
                    tasks.append(cocotb.start_soon(
                        self.master_write(m_idx, addr, data, bpw, txn_id)
                    ))
        for t in tasks:
            await t.join()

    async def read_response_race(
        self,
        master_idx: int,
        slave_idx: int,
        num_concurrent: int = 8,
        ids_in_play: int = 4,
    ) -> None:
        """Many concurrent reads with overlapping IDs from a single master
        to a single slave. Stresses the per-ID response demux in
        AXI4MasterRead (v0.1.1 #3).
        """
        base = self._parse_addr(self.slave_descs[slave_idx]["base_addr"])
        bpw = self.master_descs[master_idx]["data_width"] // 8
        tasks = []
        for n in range(num_concurrent):
            addr = base + (n * bpw)
            txn_id = n % ids_in_play
            tasks.append(cocotb.start_soon(
                self.master_read(master_idx, addr, bpw, txn_id)
            ))
        for t in tasks:
            await t.join()

    # ---------- Verification ----------

    async def settle(self, cycles: int = 200) -> None:
        """Idle the bus long enough for in-flight responses to drain."""
        await ClockCycles(self.clock, cycles)

    def verify_scoreboard(self, *, log_summary: bool = True) -> bool:
        results = self.sb.verify(self.slave_mem_read)
        if log_summary:
            self.log.info(f"Scoreboard verification:\n{results.summary()}")
        return results.passed

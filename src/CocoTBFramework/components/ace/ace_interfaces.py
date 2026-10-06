# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: ACE interface classes
# Purpose: AXI4-ACE master/snoop BFM classes.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-05

"""ACE interface classes.

This module provides the four ACE BFM classes:

- ``AXI4ACEMasterRead``: coherent read master with ARSNOOP and RACK
- ``AXI4ACEMasterWrite``: coherent write master with AWSNOOP and WACK
- ``AXI4ACESnoopSlave``: cache-side snoop responder (AC in, CR/CD out)
- ``AXI4ACESnoopMaster``: CCU-side snoop initiator (AC out, CR/CD in)

The two master classes subclass the AXI4 master classes and reuse their
transaction logic; they only replace the field configs and add the ACE
acknowledge pulses. The snoop classes are new because the AC/CR/CD channels
have no AXI4 equivalent.
"""

import collections
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

import cocotb
from cocotb.triggers import Event, RisingEdge

from CocoTBFramework.components.axi4.axi4_interfaces import (
    AXI4MasterRead,
    AXI4MasterWrite,
)
from CocoTBFramework.components.gaxi.gaxi_master import GAXIMaster
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave

from .ace_field_configs import AXI4ACEFieldConfigHelper
from .ace_packet import ACEPacket, SnoopPacket
from .ace_transaction import (
    ACETransactionType,
    CRRESP,
    CacheState,
    SnoopType,
)


@dataclass
class SnoopResult:
    """Result returned by ``AXI4ACESnoopMaster.issue_snoop``."""

    crresp: CRRESP
    data: List[int]
    latency: int  # cycles from AC issue to CR handshake


class AXI4ACEMasterRead(AXI4MasterRead):
    """ACE master read interface.

    Extends ``AXI4MasterRead`` with ARSNOOP and an optional RACK auto-pulse.
    When this BFM plays master against a DUT slave it owns ``m_axi_rack``;
    the main-repo RTL auto-pulse covers only DUT-as-master.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize ACE master read interface."""
        self.super_debug = True
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get("data_width", 32)
        self.id_width = kwargs.get("id_width", 8)
        self.addr_width = kwargs.get("addr_width", 32)
        self.user_width = kwargs.get("user_width", 1)
        self.multi_sig = kwargs.get("multi_sig", True)
        self.optional_fields = kwargs.get("optional_fields")
        self.timeout_cycles = kwargs.get("timeout_cycles", 5000)

        self.ar_channel = GAXIMaster(
            dut=dut,
            title=f"AR_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_ar_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="ar",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_ar_master",
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        self.r_channel = GAXISlave(
            dut=dut,
            title=f"R_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_r_field_config(
                self.id_width, self.data_width, self.user_width
            ),
            pkt_prefix="r",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_r_slave",
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        self._response_by_id = collections.defaultdict(collections.deque)
        self.r_channel.add_callback(self._on_r_response)

        # Inherit compliance-reporting API from AXI4MasterRead; no AXI4 checker
        # is instantiated because this is an ACE interface.
        self.compliance_checker = None

        # ACE read acknowledge
        self.auto_ack = kwargs.get("auto_ack", True)
        self.rack_sig = getattr(dut, f"{prefix}rack", None)
        self._rvalid_sig = getattr(dut, f"{prefix}rvalid", None)
        self._rready_sig = getattr(dut, f"{prefix}rready", None)
        self._rlast_sig = getattr(dut, f"{prefix}rlast", None)
        if self.auto_ack and self.rack_sig is not None and clock is not None:
            cocotb.start_soon(self._rack_pulser())

    async def read_transaction(
        self, address: int, burst_len: int = 1, **transaction_kwargs
    ) -> List[int]:
        """High-level coherent read transaction.

        Args:
            address: Read address
            burst_len: Number of beats
            **transaction_kwargs: AXI4 read fields plus ``snoop_type``

        Returns:
            List of read data values
        """
        snoop_type = transaction_kwargs.pop("snoop_type", ACETransactionType.READ_SHARED)

        ar_packet = self.ar_channel.create_packet(
            addr=address,
            len=burst_len - 1,
            id=transaction_kwargs.get("id", 0),
            size=transaction_kwargs.get("size", (self.data_width // 8).bit_length() - 1),
            burst=transaction_kwargs.get("burst_type", 1),
            lock=transaction_kwargs.get("lock", 0),
            cache=transaction_kwargs.get("cache", 0),
            prot=transaction_kwargs.get("prot", 0),
            qos=transaction_kwargs.get("qos", 0),
            region=transaction_kwargs.get("region", 0),
            snoop=int(snoop_type),
        )
        if "user" in transaction_kwargs and hasattr(ar_packet, "user"):
            ar_packet.user = transaction_kwargs["user"]

        await self.ar_channel.send(ar_packet)

        txn_id = transaction_kwargs.get("id", 0)
        id_queue = self._response_by_id[txn_id]
        cycles_waited = 0
        while len(id_queue) < burst_len:
            await RisingEdge(self.clock)
            cycles_waited += 1
            if cycles_waited > self.timeout_cycles:
                received = len(id_queue)
                raise TimeoutError(
                    f"AXI4-ACE read timeout after {cycles_waited} cycles: "
                    f"got {received} of {burst_len} responses at address 0x{address:08X} "
                    f"(id={txn_id})"
                )

        read_data = []
        for _ in range(burst_len):
            packet = id_queue.popleft()
            data_value = getattr(packet, "data", 0)
            read_data.append(data_value)
            if hasattr(packet, "resp") and packet.resp != 0:
                resp_names = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
                resp_name = resp_names.get(packet.resp, "UNKNOWN")
                raise RuntimeError(f"AXI4-ACE read error: {resp_name} (0x{packet.resp:X})")

        return read_data

    async def _rack_pulser(self):
        """Pulse RACK one cycle after each RLAST handshake.

        The RTL modules in the main repo auto-pulse RACK only when the DUT is
        the master. When this BFM plays master against a DUT slave, the BFM
        itself must drive the acknowledge.
        """
        try:
            while True:
                await RisingEdge(self.clock)
                if (
                    self._rvalid_sig is not None
                    and self._rready_sig is not None
                    and self._rlast_sig is not None
                ):
                    if (
                        bool(self._rvalid_sig.value)
                        and bool(self._rready_sig.value)
                        and bool(self._rlast_sig.value)
                    ):
                        await RisingEdge(self.clock)
                        self.rack_sig.setimmediatevalue(1)
                        await RisingEdge(self.clock)
                        self.rack_sig.setimmediatevalue(0)
        except Exception as e:
            if self.log:
                self.log.debug(f"AXI4ACEMasterRead RACK pulser stopped: {e}")


class AXI4ACEMasterWrite(AXI4MasterWrite):
    """ACE master write interface.

    Extends ``AXI4MasterWrite`` with AWSNOOP and an optional WACK auto-pulse.
    When this BFM plays master against a DUT slave it owns ``m_axi_wack``;
    the main-repo RTL auto-pulse covers only DUT-as-master.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize ACE master write interface."""
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get("data_width", 32)
        self.id_width = kwargs.get("id_width", 8)
        self.addr_width = kwargs.get("addr_width", 32)
        self.user_width = kwargs.get("user_width", 1)
        self.multi_sig = kwargs.get("multi_sig", True)
        self.optional_fields = kwargs.get("optional_fields")
        self.timeout_cycles = kwargs.get("timeout_cycles", 5000)

        self.aw_channel = GAXIMaster(
            dut=dut,
            title=f"AW_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_aw_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="aw",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_aw_master",
            log=log,
            optional_fields=self.optional_fields,
        )

        self.w_channel = GAXIMaster(
            dut=dut,
            title=f"W_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_w_field_config(
                self.data_width, self.user_width
            ),
            pkt_prefix="w",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_w_master",
            log=log,
            optional_fields=self.optional_fields,
        )

        self.b_channel = GAXISlave(
            dut=dut,
            title=f"B_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_b_field_config(
                self.id_width, self.user_width
            ),
            pkt_prefix="b",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_b_slave",
            log=log,
            optional_fields=self.optional_fields,
        )

        self._response_by_id = collections.defaultdict(collections.deque)
        self.b_channel.add_callback(self._on_b_response)

        # Inherit compliance-reporting API from AXI4MasterWrite; no AXI4 checker
        # is instantiated because this is an ACE interface.
        self.compliance_checker = None

        from cocotb.triggers import Lock
        self._aw_lock = Lock(name=f"AW_Lock{self.ifc_name}")
        self._w_prev_done = None

        # ACE write acknowledge
        self.auto_ack = kwargs.get("auto_ack", True)
        self.wack_sig = getattr(dut, f"{prefix}wack", None)
        self._bvalid_sig = getattr(dut, f"{prefix}bvalid", None)
        self._bready_sig = getattr(dut, f"{prefix}bready", None)
        if self.auto_ack and self.wack_sig is not None and clock is not None:
            cocotb.start_soon(self._wack_pulser())

    async def write_transaction(
        self,
        address: int,
        data: Union[int, List[int]],
        burst_len: Optional[int] = None,
        **transaction_kwargs,
    ) -> Dict[str, Any]:
        """High-level coherent write transaction.

        Args:
            address: Write address
            data: Write data (single value or list for burst)
            burst_len: Burst length
            **transaction_kwargs: AXI4 write fields plus ``snoop_type``

        Returns:
            Response dictionary
        """
        snoop_type = transaction_kwargs.pop("snoop_type", ACETransactionType.WRITE_UNIQUE)
        aw_packet = None

        try:
            if isinstance(data, list):
                data_list = data
                if burst_len is None:
                    burst_len = len(data_list)
                else:
                    data_list = data_list[:burst_len]
            else:
                if burst_len is None:
                    burst_len = 1
                data_list = [data] * burst_len

            txn_id = transaction_kwargs.get("id", 0)
            full_bus_size = (self.data_width // 8).bit_length() - 1

            aw_packet = self.aw_channel.create_packet(
                addr=address,
                len=burst_len - 1,
                id=txn_id,
                size=transaction_kwargs.get("size", full_bus_size),
                burst=transaction_kwargs.get("burst_type", 1),
                lock=transaction_kwargs.get("lock", 0),
                cache=transaction_kwargs.get("cache", 0),
                prot=transaction_kwargs.get("prot", 0),
                qos=transaction_kwargs.get("qos", 0),
                region=transaction_kwargs.get("region", 0),
                snoop=int(snoop_type),
            )
            if "user" in transaction_kwargs and hasattr(aw_packet, "user"):
                aw_packet.user = transaction_kwargs["user"]

            my_w_done = Event(name=f"W_Done{self.ifc_name}")
            async with self._aw_lock:
                prev_w_done = self._w_prev_done
                self._w_prev_done = my_w_done
                await self.aw_channel.send(aw_packet)

            try:
                if prev_w_done is not None:
                    await prev_w_done.wait()

                strb_width = self.data_width // 8
                beat_bytes = 1 << aw_packet.size
                w_packets = []
                for i, data_value in enumerate(data_list):
                    if "strb" in transaction_kwargs:
                        beat_strb = transaction_kwargs["strb"]
                    elif beat_bytes >= strb_width:
                        beat_strb = (1 << strb_width) - 1
                    else:
                        lane = (address + i * beat_bytes) % strb_width
                        beat_strb = ((1 << beat_bytes) - 1) << lane
                        data_value = (data_value & ((1 << (beat_bytes * 8)) - 1)) << (lane * 8)
                    w_packets.append(self.w_channel.create_packet(
                        data=data_value,
                        last=1 if i == len(data_list) - 1 else 0,
                        strb=beat_strb,
                        **{k: v for k, v in transaction_kwargs.items() if k.startswith("w")}
                    ))
                await self.w_channel.send_burst(w_packets)
            finally:
                my_w_done.set()

            id_queue = self._response_by_id[txn_id]
            cycles_waited = 0
            while len(id_queue) < 1:
                await RisingEdge(self.clock)
                cycles_waited += 1
                if cycles_waited > self.timeout_cycles:
                    raise TimeoutError(
                        f"AXI4-ACE write timeout after {cycles_waited} cycles: "
                        f"waiting for B response at address 0x{address:08X} "
                        f"(id={txn_id})"
                    )

            b_response = id_queue.popleft()
            resp_code = b_response.resp if hasattr(b_response, "resp") else 0
            result = {"success": True, "response": resp_code, "id": b_response.id if hasattr(b_response, "id") else 0}
            if resp_code != 0:
                resp_names = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
                resp_name = resp_names.get(resp_code, "UNKNOWN")
                result["success"] = False
                result["error"] = f"AXI4-ACE write error: {resp_name} (0x{resp_code:X})"
                if self.log:
                    self.log.error(
                        f"AXI4-ACE write transaction failed: addr=0x{address:08X}, "
                        f"error: {result['error']}"
                    )
            return result

        except Exception as e:
            if self.log:
                addr_str = f"addr=0x{address:08X}" if address is not None else "addr=None"
                data_str = f"data=0x{data:08X}" if isinstance(data, int) else f"data={type(data).__name__}"
                packet_str = f"aw_packet={'created' if aw_packet is not None else 'not_created'}"
                self.log.error(
                    f"AXI4-ACE write transaction failed: {addr_str}, {data_str}, "
                    f"{packet_str}, error: {str(e)}"
                )
            return {"success": False, "error": str(e), "response": None, "id": None}

    async def _wack_pulser(self):
        """Pulse WACK one cycle after each B handshake."""
        try:
            while True:
                await RisingEdge(self.clock)
                if (
                    self._bvalid_sig is not None
                    and self._bready_sig is not None
                ):
                    if bool(self._bvalid_sig.value) and bool(self._bready_sig.value):
                        await RisingEdge(self.clock)
                        self.wack_sig.setimmediatevalue(1)
                        await RisingEdge(self.clock)
                        self.wack_sig.setimmediatevalue(0)
        except Exception as e:
            if self.log:
                self.log.debug(f"AXI4ACEMasterWrite WACK pulser stopped: {e}")


class AXI4ACESnoopSlave:
    """ACE snoop slave (cache-side responder).

    Receives snoop addresses on AC, drives CR and CD in AC-issue order. The
    family adapter convention (stricter than the spec) requires that all CD
    beats for snoop N complete before CR for snoop N is asserted.

    A programmable MESI responder model is provided via ``set_line_behavior``,
    plus an injection point for a custom handler.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize ACE snoop slave interface."""
        self.dut = dut
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get("data_width", 32)
        self.addr_width = kwargs.get("addr_width", 32)
        self.user_width = kwargs.get("user_width", 1)
        self.multi_sig = kwargs.get("multi_sig", True)
        self.optional_fields = kwargs.get("optional_fields")

        # AC channel: manager -> cache
        self.ac_channel = GAXISlave(
            dut=dut,
            title=f"AC_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_ac_field_config(self.addr_width),
            pkt_prefix="ac",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_ac_slave",
            log=log,
            optional_fields=self.optional_fields,
        )

        # CR channel: cache -> manager
        self.cr_channel = GAXIMaster(
            dut=dut,
            title=f"CR_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_cr_field_config(),
            pkt_prefix="cr",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_cr_master",
            log=log,
            optional_fields=self.optional_fields,
        )

        # CD channel: cache -> manager
        self.cd_channel = GAXIMaster(
            dut=dut,
            title=f"CD_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_cd_field_config(self.data_width),
            pkt_prefix="cd",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_cd_master",
            log=log,
            optional_fields=self.optional_fields,
        )

        # Responder state: address -> CacheState
        self.line_behaviors: Dict[int, CacheState] = {}

        # Optional user-supplied handler: (addr, snoop_type, state) -> (crresp, data|None)
        self.user_handler: Optional[Callable[[int, SnoopType, CacheState], tuple]] = None

        # Pending snoop queue and active responder
        self._pending_snoops: collections.deque = collections.deque()
        self._responder_active = False
        self._seq_counter = 0

        self.ac_channel.add_callback(self._ac_callback)

    def set_line_behavior(self, addr: int, state: CacheState) -> None:
        """Set the expected cache-line state for ``addr``."""
        self.line_behaviors[addr] = CacheState(state)

    def set_handler(
        self,
        handler: Callable[[int, SnoopType, CacheState], tuple],
    ) -> None:
        """Install a custom snoop handler.

        The handler receives ``(addr, snoop_type, state)`` and must return
        ``(crresp, data_or_None)``. ``data_or_None`` may be a single integer
        for one beat or a list of integers for a multi-beat response.
        """
        self.user_handler = handler

    def _state_for_addr(self, addr: int) -> CacheState:
        """Return the configured state for an address, defaulting to Invalid."""
        return self.line_behaviors.get(addr, CacheState.INVALID)

    def _default_handler(
        self,
        addr: int,
        snoop_type: SnoopType,
        state: CacheState,
    ) -> tuple:
        """Default MESI snoop response matrix.

        Returns ``(crresp, data_or_None)`` where ``data_or_None`` may be a
        single integer or a list of integers.
        """
        if state == CacheState.INVALID:
            return CRRESP(0), None

        if state == CacheState.SHARED:
            if snoop_type in (SnoopType.READ_SHARED, SnoopType.READ_ONCE):
                return CRRESP.from_bits(is_shared=True), None
            if snoop_type == SnoopType.READ_UNIQUE:
                return CRRESP(0), None
            # CleanShared / CleanInvalid / MakeInvalid
            return CRRESP(0), None

        if state == CacheState.EXCLUSIVE:
            if snoop_type in (SnoopType.READ_SHARED, SnoopType.READ_ONCE):
                # Supply data, line becomes Shared
                return CRRESP.from_bits(data_transfer=True, is_shared=True, was_unique=True), 0
            if snoop_type == SnoopType.READ_UNIQUE:
                return CRRESP.from_bits(data_transfer=True, was_unique=True), 0
            if snoop_type == SnoopType.CLEAN_SHARED:
                return CRRESP.from_bits(is_shared=True, was_unique=True), None
            # CleanInvalid / MakeInvalid
            return CRRESP(0), None

        if state == CacheState.MODIFIED:
            if snoop_type == SnoopType.READ_SHARED:
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), 0
            if snoop_type == SnoopType.READ_UNIQUE:
                return CRRESP.from_bits(data_transfer=True, pass_dirty=True), 0
            if snoop_type in (SnoopType.CLEAN_SHARED, SnoopType.CLEAN_INVALID):
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), 0
            if snoop_type == SnoopType.MAKE_INVALID:
                # Invalidate without data (IHI0022: MakeInvalid forbids
                # DataTransfer; enforced by CRRESP.validate_for_snoop).
                return CRRESP(0), None
            if snoop_type == SnoopType.READ_ONCE:
                return CRRESP.from_bits(data_transfer=True, pass_dirty=True), 0

        if state == CacheState.OWNED:
            if snoop_type in (SnoopType.READ_SHARED, SnoopType.READ_ONCE):
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), 0
            if snoop_type == SnoopType.READ_UNIQUE:
                return CRRESP.from_bits(data_transfer=True, pass_dirty=True, is_shared=True), 0
            if snoop_type in (SnoopType.CLEAN_SHARED, SnoopType.CLEAN_INVALID):
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), 0
            if snoop_type == SnoopType.MAKE_INVALID:
                # Invalidate without data (IHI0022: MakeInvalid forbids
                # DataTransfer; enforced by CRRESP.validate_for_snoop).
                return CRRESP(0), None

        # Safe fallback
        return CRRESP(0), None

    def _handle_snoop(
        self,
        addr: int,
        snoop_type: SnoopType,
    ) -> SnoopPacket:
        """Resolve a snoop to a response packet, validating CRRESP."""
        state = self._state_for_addr(addr)

        if self.user_handler is not None:
            crresp, data = self.user_handler(addr, snoop_type, state)
        else:
            crresp, data = self._default_handler(addr, snoop_type, state)

        if not isinstance(crresp, CRRESP):
            crresp = CRRESP(crresp)

        valid, msg = crresp.validate_for_snoop(snoop_type)
        if not valid:
            if self.log:
                self.log.error(f"AXI4ACESnoopSlave: CRRESP protocol violation: {msg}")
            else:
                raise RuntimeError(f"CRRESP protocol violation: {msg}")

        if data is None:
            beats = []
        elif isinstance(data, list):
            beats = data
        else:
            beats = [data]

        return SnoopPacket(addr, snoop_type, crresp, beats, len(beats))

    def _ac_callback(self, ac_packet):
        """Handle incoming AC packet."""
        addr = getattr(ac_packet, "addr", 0)
        snoop_val = getattr(ac_packet, "snoop", 0)
        try:
            snoop_type = SnoopType(snoop_val)
        except ValueError:
            snoop_type = SnoopType.READ_ONCE
            if self.log:
                self.log.warning(f"AXI4ACESnoopSlave: unknown ACSNOOP value {snoop_val}")

        seq = self._seq_counter
        self._seq_counter += 1

        self._pending_snoops.append({
            "addr": addr,
            "snoop_type": snoop_type,
            "seq": seq,
        })

        if self.log:
            self.log.debug(
                f"AXI4ACESnoopSlave: AC received - addr=0x{addr:08X}, "
                f"snoop={snoop_type.name}, seq={seq}"
            )

        if not self._responder_active:
            self._responder_active = True
            cocotb.start_soon(self._snoop_responder())

    async def _snoop_responder(self):
        """Process pending snoops in order, sending CD then CR."""
        try:
            while self._pending_snoops:
                pending = self._pending_snoops.popleft()
                result = self._handle_snoop(pending["addr"], pending["snoop_type"])

                # Send all CD beats first (family convention)
                for i, beat in enumerate(result.data):
                    cd_packet = self.cd_channel.create_packet(
                        data=beat,
                        last=int(i == len(result.data) - 1),
                    )
                    await self.cd_channel.send(cd_packet)

                # Then send CR
                cr_packet = self.cr_channel.create_packet(resp=int(result.crresp))
                await self.cr_channel.send(cr_packet)

                if self.log:
                    self.log.debug(
                        f"AXI4ACESnoopSlave: responded to snoop seq={pending['seq']} "
                        f"with crresp={result.crresp}, beats={result.beats}"
                    )
        except Exception as e:
            if self.log:
                self.log.error(f"AXI4ACESnoopSlave: responder error: {e}")
        finally:
            self._responder_active = False


class AXI4ACESnoopMaster:
    """ACE snoop master (CCU-side initiator).

    Drives snoop addresses on AC and gathers CR/CD responses in issue order.
    By default only one outstanding snoop is allowed per attached cache,
    matching the RTL bring-up convention.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize ACE snoop master interface."""
        self.dut = dut
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get("data_width", 32)
        self.addr_width = kwargs.get("addr_width", 32)
        self.multi_sig = kwargs.get("multi_sig", True)
        self.optional_fields = kwargs.get("optional_fields")
        self.timeout_cycles = kwargs.get("timeout_cycles", 5000)
        self.allow_multiple_outstanding = kwargs.get("allow_multiple_outstanding", False)

        # AC channel: CCU -> cache
        self.ac_channel = GAXIMaster(
            dut=dut,
            title=f"AC_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_ac_field_config(self.addr_width),
            pkt_prefix="ac",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_ac_master",
            log=log,
            optional_fields=self.optional_fields,
        )

        # CR channel: cache -> CCU
        self.cr_channel = GAXISlave(
            dut=dut,
            title=f"CR_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_cr_field_config(),
            pkt_prefix="cr",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_cr_slave",
            log=log,
            optional_fields=self.optional_fields,
        )

        # CD channel: cache -> CCU
        self.cd_channel = GAXISlave(
            dut=dut,
            title=f"CD_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4ACEFieldConfigHelper.create_cd_field_config(self.data_width),
            pkt_prefix="cd",
            multi_sig=self.multi_sig,
            protocol_type="axi4ace_cd_slave",
            log=log,
            optional_fields=self.optional_fields,
        )

        self._outstanding = False
        self._exclude_addr: Optional[Callable[[int], bool]] = kwargs.get("exclude_addr")
        self._exclude_source: Optional[Callable[[], bool]] = kwargs.get("exclude_source")

    def _should_exclude(self, addr: int) -> bool:
        """Check whether a snoop to ``addr`` should be suppressed."""
        if self._exclude_addr is not None and self._exclude_addr(addr):
            return True
        if self._exclude_source is not None and self._exclude_source():
            return True
        return False

    async def issue_snoop(self, addr: int, snoop_type: SnoopType) -> SnoopResult:
        """Issue a single snoop and return its CR/CD result.

        Args:
            addr: Snoop address
            snoop_type: Type of snoop to issue

        Returns:
            SnoopResult with crresp, data beats, and latency
        """
        if not self.allow_multiple_outstanding and self._outstanding:
            raise RuntimeError(
                "AXI4ACESnoopMaster: outstanding snoop already in flight "
                "(allow_multiple_outstanding=False)"
            )

        if self._should_exclude(addr):
            if self.log:
                self.log.warning(
                    f"AXI4ACESnoopMaster: suppressed snoop to excluded address 0x{addr:08X}"
                )
            return SnoopResult(CRRESP(0), [], 0)

        self._outstanding = True
        start_cycle = cocotb.utils.get_sim_time("ns")

        ac_packet = self.ac_channel.create_packet(
            addr=addr,
            snoop=int(snoop_type),
            prot=0,
        )
        await self.ac_channel.send(ac_packet)

        # Wait for CR response
        cr_packet = await self._recv_cr()
        crresp = CRRESP(getattr(cr_packet, "resp", 0))

        # Collect CD beats if CR indicated data transfer
        data = []
        if crresp.data_transfer:
            data = await self._recv_cd()

        end_cycle = cocotb.utils.get_sim_time("ns")
        # Latency in clock cycles: assume clock period in ns is not known,
        # so report 0 unless a caller overrides. Tests can check data/order.
        latency = 0

        self._outstanding = False
        return SnoopResult(crresp, data, latency)

    async def _recv_cr(self):
        """Wait for the next CR packet."""
        cycles = 0
        while not self.cr_channel._recvQ:
            await RisingEdge(self.clock)
            cycles += 1
            if cycles > self.timeout_cycles:
                raise TimeoutError("AXI4ACESnoopMaster: timeout waiting for CR response")
        return self.cr_channel._recvQ.popleft()

    async def _recv_cd(self) -> List[int]:
        """Collect CD beats until CDLAST."""
        beats = []
        cycles = 0
        while True:
            while not self.cd_channel._recvQ:
                await RisingEdge(self.clock)
                cycles += 1
                if cycles > self.timeout_cycles:
                    raise TimeoutError("AXI4ACESnoopMaster: timeout waiting for CD beats")
            pkt = self.cd_channel._recvQ.popleft()
            beats.append(getattr(pkt, "data", 0))
            if getattr(pkt, "last", 0):
                break
        return beats

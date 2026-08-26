# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI4MasterRead
# Purpose: AXI4 Interface Classes - Enhanced with Integrated Compliance Checking
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXI4 Interface Classes - Enhanced with Integrated Compliance Checking

MODIFICATION: Added seamless compliance checking integration to all AXI4 interfaces
without changing any existing APIs or requiring testbench modifications.

The compliance checker is automatically enabled when AXI4_COMPLIANCE_CHECK=1 is set
and silently disabled otherwise, maintaining full backward compatibility.
"""

import collections
import random
from typing import Any, Dict, List, Optional, Union

import cocotb
from cocotb.triggers import Lock, RisingEdge

from CocoTBFramework.components.axi4.axi4_compliance_checker import AXI4ComplianceChecker
from CocoTBFramework.components.axi4.axi4_field_configs import AXI4FieldConfigHelper
from CocoTBFramework.components.axi4.axi4_packet import AXI4Packet

# Import GAXI components and field configs
from CocoTBFramework.components.gaxi.gaxi_master import GAXIMaster
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave


class AXI4MasterRead:
    """
    AXI4 Master Read Interface - Enhanced with integrated compliance checking.

    Manages read address requests (AR) and read data responses (R).

    ENHANCEMENT: Automatically includes compliance checking when enabled via environment.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI4 Master Read interface with optional compliance checking."""
        self.super_debug = True
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        # Extract configuration parameters
        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)  # AXI4 uses individual signals by default
        # Fields the DUT genuinely does not carry (e.g. AxREGION on an AXI5
        # port -- AMBA5 removed it). Declared fields otherwise bind fatally.
        self.optional_fields = kwargs.get('optional_fields')

        # AR Channel (Address Read) - Master drives
        self.ar_channel = GAXIMaster(
            dut=dut,
            title=f"AR_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_ar_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="ar",
            multi_sig=self.multi_sig,
            protocol_type='axi4_ar_master',  # Use AXI4-specific patterns
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        # R Channel needs to drive rready - use GAXISlave
        self.r_channel = GAXISlave(
            dut=dut,
            title=f"R_Slave{self.ifc_name}",  # Slave role - drives rready, receives R data
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_r_field_config(
                self.id_width, self.data_width, self.user_width
            ),
            pkt_prefix="r",
            multi_sig=self.multi_sig,
            protocol_type='axi4_r_slave',  # Use AXI4-specific patterns
            super_debug=self.super_debug,
            log=log
        )

        # Store parameters for transaction methods
        # Large timeout to handle worst-case backpressure through skid buffers
        self.timeout_cycles = kwargs.get('timeout_cycles', 5000)

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXI4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            id_width=self.id_width,
            addr_width=self.addr_width,
            user_width=self.user_width,
            multi_sig=self.multi_sig
        )

        if self.compliance_checker and log:
            log.info("AXI4MasterRead: Compliance checking enabled")

        # Per-ID response FIFO for concurrent read_transaction() pickup.
        # Positional indexing into self.r_channel._recvQ races when callers
        # use cocotb.start_soon to dispatch overlapping transactions: every
        # coroutine snapshots initial_count=0 and reads _recvQ[0] as "theirs".
        # Routing each R beat into a per-ID deque via callback eliminates the
        # race -- AXI4 guarantees same-ID R beats arrive in order, so a deque
        # per ID is sufficient. (Cross-ID interleaving is handled by keying on
        # ID.) Mirrors the FIFO matching introduced for AXIL4SlaveWrite in
        # 2e7e825.
        self._response_by_id = collections.defaultdict(collections.deque)
        self.r_channel.add_callback(self._on_r_response)

    def _on_r_response(self, pkt):
        """Route incoming R beat into its per-ID deque (see __init__ rationale)."""
        pkt_id = getattr(pkt, 'id', 0)
        self._response_by_id[pkt_id].append(pkt)

    async def read_transaction(self, address: int, burst_len: int = 1, **transaction_kwargs) -> List[int]:
        """
        High-level read transaction using generic field names.

        Concurrency-safe: pickup is keyed on transaction ID via
        self._response_by_id (populated by _on_r_response callback).
        Sequential callers behave identically -- with only one outstanding
        transaction per ID, the per-ID deque sees the same packets in the
        same order as the previous positional _recvQ[initial_count + i].
        """
        txn_id = transaction_kwargs.get('id', 0)

        # Default ARSIZE is the full bus width. A fixed size=2 (4 bytes)
        # default silently under-sized every beat on >32-bit buses: the
        # slave then legally returns only a 4-byte lane slice, which is
        # never what a caller passing full-width data words meant.
        full_bus_size = (self.data_width // 8).bit_length() - 1

        # Create AR packet with GENERIC field names
        ar_packet = self.ar_channel.create_packet(
            addr=address,
            len=burst_len - 1,
            id=txn_id,
            size=transaction_kwargs.get('size', full_bus_size),
            burst=transaction_kwargs.get('burst_type', 1),
            lock=transaction_kwargs.get('lock', 0),
            cache=transaction_kwargs.get('cache', 0),
            prot=transaction_kwargs.get('prot', 0),
            qos=transaction_kwargs.get('qos', 0),
            region=transaction_kwargs.get('region', 0),
        )

        # Apply optional user field after creation (referencing ar_packet
        # inside its own create_packet() call was a NameError when 'user'
        # was passed).
        if 'user' in transaction_kwargs and hasattr(ar_packet, 'user'):
            ar_packet.user = transaction_kwargs['user']

        # Send read address
        await self.ar_channel.send(ar_packet)

        # Wait for burst_len R beats in our ID's deque
        id_queue = self._response_by_id[txn_id]
        cycles_waited = 0
        while len(id_queue) < burst_len:
            await RisingEdge(self.clock)
            cycles_waited += 1

            if cycles_waited > self.timeout_cycles:
                received = len(id_queue)
                raise TimeoutError(f"AXI4 read timeout after {cycles_waited} cycles: "
                                    f"got {received} of {burst_len} responses at address 0x{address:08X} "
                                    f"(id={txn_id})")

        # Drain burst_len beats from this ID's queue
        read_data = []
        for _ in range(burst_len):
            packet = id_queue.popleft()
            data_value = getattr(packet, 'data', 0)
            read_data.append(data_value)

            # Check for errors using GENERIC field names
            if hasattr(packet, 'resp') and packet.resp != 0:
                resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
                resp_name = resp_names.get(packet.resp, 'UNKNOWN')
                raise RuntimeError(f"AXI4 read error: {resp_name} (0x{packet.resp:X})")

        return read_data

    async def single_read(self, address: int, **kwargs) -> int:
        """Convenience method for single read. UNCHANGED."""
        data_list = await self.read_transaction(address, burst_len=1, **kwargs)
        return data_list[0]

    def create_ar_packet(self, **kwargs) -> AXI4Packet:
        """Create AR packet with current configuration using generic field names. UNCHANGED."""
        return self.ar_channel.create_packet(**kwargs)

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """
        ENHANCEMENT: Get compliance report if compliance checking is enabled.

        Returns:
            Compliance report dictionary or None if compliance checking disabled
        """
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """ENHANCEMENT: Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXI4MasterRead: Compliance checking is disabled")


class AXI4MasterWrite:
    """
    AXI4 Master Write Interface - Enhanced with integrated compliance checking.

    Manages write address requests (AW), write data (W), and write responses (B).

    ENHANCEMENT: Automatically includes compliance checking when enabled via environment.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI4 Master Write interface with optional compliance checking."""
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        # Extract configuration parameters
        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)  # AXI4 uses individual signals by default
        # Fields the DUT genuinely does not carry (e.g. AxREGION on an AXI5
        # port -- AMBA5 removed it). Declared fields otherwise bind fatally.
        self.optional_fields = kwargs.get('optional_fields')

        # AW Channel (Address Write) - Master drives
        self.aw_channel = GAXIMaster(
            dut=dut,
            title=f"AW_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_aw_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="aw",
            multi_sig=self.multi_sig,
            protocol_type='axi4_aw_master',  # Use AXI4-specific patterns
            log=log,
            optional_fields=self.optional_fields,
        )

        # W Channel (Write Data) - Master drives
        self.w_channel = GAXIMaster(
            dut=dut,
            title=f"W_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_w_field_config(
                self.data_width, self.user_width
            ),
            pkt_prefix="w",
            multi_sig=self.multi_sig,
            protocol_type='axi4_w_master',  # Use AXI4-specific patterns
            log=log
        )

        # B Channel (Write Response) - Slave receives responses
        self.b_channel = GAXISlave(
            dut=dut,
            title=f"B_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_b_field_config(
                self.id_width, self.user_width
            ),
            pkt_prefix="b",
            multi_sig=self.multi_sig,
            protocol_type='axi4_b_slave',  # Use AXI4-specific patterns
            log=log
        )

        # Store parameters for transaction methods
        # Large timeout to handle worst-case backpressure through skid buffers
        self.timeout_cycles = kwargs.get('timeout_cycles', 5000)

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXI4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            id_width=self.id_width,
            addr_width=self.addr_width,
            user_width=self.user_width,
            multi_sig=self.multi_sig
        )

        if self.compliance_checker and log:
            log.info("AXI4MasterWrite: Compliance checking enabled")

        # Per-ID B-response FIFO for concurrent write_transaction() pickup.
        # See AXI4MasterRead.__init__ for race rationale. AXI4 guarantees one
        # B response per AW transaction and same-ID B responses arrive in
        # order, so a deque per ID is sufficient.
        self._response_by_id = collections.defaultdict(collections.deque)
        self.b_channel.add_callback(self._on_b_response)

        # AW+W issuance lock. AXI4 requires W beats to arrive in the order
        # of their corresponding AWs (matched by AWLEN/WLAST -- W has no ID).
        # Without serialization, two concurrent write_transaction() calls
        # interleave W beats on the wire: AW0's burst gets AW1's W data
        # and vice versa. Lock the entire (send AW, send all W beats)
        # critical section so each transaction's W stream is wire-contiguous.
        # Sequential callers see an uncontended lock -- no behavior change.
        # NOTE: cocotb.triggers.Lock (not asyncio.Lock) -- cocotb's scheduler
        # is not asyncio, so asyncio.Lock() raises NoneType.create_future on
        # acquire because there's no running asyncio loop.
        self._aw_w_lock = Lock(name=f"AW_W_Lock{self.ifc_name}")

    def _on_b_response(self, pkt):
        """Route incoming B response into its per-ID deque."""
        pkt_id = getattr(pkt, 'id', 0)
        self._response_by_id[pkt_id].append(pkt)

    async def write_transaction(self, address: int, data: Union[int, List[int]],
                            burst_len: Optional[int] = None, **transaction_kwargs) -> Dict[str, Any]:
        """
        High-level write transaction using generic field names.
        UNCHANGED: All existing functionality preserved.
        """
        # Initialize aw_packet to None to prevent UnboundLocalError
        aw_packet = None

        try:
            # Handle data formatting
            if isinstance(data, list):
                data_list = data
                if burst_len is None:
                    burst_len = len(data_list)
                else:
                    data_list = data_list[:burst_len]  # Truncate if needed
            else:
                if burst_len is None:
                    burst_len = 1
                data_list = [data] * burst_len

            txn_id = transaction_kwargs.get('id', 0)

            # Default AWSIZE is the full bus width, matching the all-lanes
            # default WSTRB below. The old fixed size=2 default contradicted
            # that strobe on >32-bit buses (AWSIZE said 4 bytes, WSTRB
            # enabled every lane) -- an AXI violation that made slaves drop
            # or mis-slice the write.
            full_bus_size = (self.data_width // 8).bit_length() - 1

            # Create AW packet with GENERIC field names
            aw_packet = self.aw_channel.create_packet(
                addr=address,
                len=burst_len - 1,
                id=txn_id,
                size=transaction_kwargs.get('size', full_bus_size),
                burst=transaction_kwargs.get('burst_type', 1),
                lock=transaction_kwargs.get('lock', 0),
                cache=transaction_kwargs.get('cache', 0),
                prot=transaction_kwargs.get('prot', 0),
                qos=transaction_kwargs.get('qos', 0),
                region=transaction_kwargs.get('region', 0),
            )

            # Apply optional user field after creation (the old inline
            # hasattr(aw_packet, ...) check ran before aw_packet was bound,
            # so a caller-supplied 'user' was silently dropped).
            if 'user' in transaction_kwargs and hasattr(aw_packet, 'user'):
                aw_packet.user = transaction_kwargs['user']

            # Serialize AW+W issuance so concurrent same-ID write_transaction
            # calls don't interleave W beats on the wire (see __init__).
            async with self._aw_w_lock:
                # Send address
                await self.aw_channel.send(aw_packet)

                # Send data beats using GENERIC field names
                strb_width = self.data_width // 8
                beat_bytes = 1 << aw_packet.size

                for i, data_value in enumerate(data_list):
                    if 'strb' in transaction_kwargs:
                        beat_strb = transaction_kwargs['strb']
                    elif beat_bytes >= strb_width:
                        beat_strb = (1 << strb_width) - 1  # All bytes enabled
                    else:
                        # Narrow write: enable only this beat's addressed
                        # lanes (INCR walks the lanes beat by beat). Strobes
                        # outside the AWSIZE window are an AXI violation.
                        # The data value is lane-positioned to match -- on
                        # the wire, narrow data rides in the addressed lanes.
                        lane = (address + i * beat_bytes) % strb_width
                        beat_strb = ((1 << beat_bytes) - 1) << lane
                        data_value = (data_value & ((1 << (beat_bytes * 8)) - 1)) << (lane * 8)
                    w_packet = self.w_channel.create_packet(
                        data=data_value,
                        last=1 if i == len(data_list) - 1 else 0,
                        strb=beat_strb,
                        **{k: v for k, v in transaction_kwargs.items() if k.startswith('w')}
                    )
                    await self.w_channel.send(w_packet)

            # Wait for B response in this transaction's ID deque.
            # See AXI4MasterRead.read_transaction for concurrency rationale --
            # positional _recvQ indexing races under cocotb.start_soon.
            id_queue = self._response_by_id[txn_id]
            cycles_waited = 0
            while len(id_queue) < 1:
                await RisingEdge(self.clock)
                cycles_waited += 1

                if cycles_waited > self.timeout_cycles:
                    raise TimeoutError(f"AXI4 write timeout after {cycles_waited} cycles: "
                                        f"waiting for B response at address 0x{address:08X} "
                                        f"(id={txn_id})")

            # Pop our B response from this ID's queue
            b_response = id_queue.popleft()

            # Check for errors using GENERIC field names
            if hasattr(b_response, 'resp') and b_response.resp != 0:
                resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
                resp_name = resp_names.get(b_response.resp, 'UNKNOWN')
                raise RuntimeError(f"AXI4 write error: {resp_name} (0x{b_response.resp:X})")

            return {
                'success': True,
                'response': b_response.resp if hasattr(b_response, 'resp') else 0,
                'id': b_response.id if hasattr(b_response, 'id') else 0
            }

        except Exception as e:
            # Log the error with details about what we tried to do
            if self.log:
                addr_str = f"addr=0x{address:08X}" if address is not None else "addr=None"
                data_str = f"data=0x{data:08X}" if isinstance(data, int) else f"data={type(data).__name__}"
                packet_str = f"aw_packet={'created' if aw_packet is not None else 'not_created'}"
                self.log.error(f"AXI4 write transaction failed: {addr_str}, {data_str}, {packet_str}, error: {str(e)}")

            # Return failure result
            return {
                'success': False,
                'error': str(e),
                'response': None,
                'id': None
            }

    async def single_write(self, address: int, data: int, **kwargs) -> Dict[str, Any]:
        """Convenience method for single write. UNCHANGED."""
        return await self.write_transaction(address, data, burst_len=1, **kwargs)

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """
        ENHANCEMENT: Get compliance report if compliance checking is enabled.

        Returns:
            Compliance report dictionary or None if compliance checking disabled
        """
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """ENHANCEMENT: Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXI4MasterWrite: Compliance checking is disabled")


class AXI4SlaveRead:
    """
    AXI4 Slave Read Interface - Enhanced with integrated compliance checking.

    Uses GAXISlave for AR (drives arready) with callback to GAXIMaster for R (drives responses).

    ENHANCEMENT: Automatically includes compliance checking when enabled via environment.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI4 Slave Read interface with proper architecture and compliance checking."""
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        # Extract configuration parameters
        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)  # AXI4 uses individual signals by default

        # Store memory model if provided
        self.memory_model = kwargs.get('memory_model')

        # Base address offset (for memory-mapped slaves)
        # If provided, incoming AXI addresses will have base_addr subtracted
        # before accessing memory_model (which expects 0-based offsets)
        self.base_addr = kwargs.get('base_addr', 0)

        # Response configuration
        self.response_delay_cycles = kwargs.get('response_delay', 1)
        # Optional response override: a callable (address) -> resp code, or
        # None to leave the natural response alone. Same convention as the
        # AXIL4 slaves; without it this BFM can only answer OKAY and a
        # DUT's R-path error handling is untestable.
        self.resp_override = kwargs.get('resp_override')

        # Out-of-order response configuration
        self.enable_ooo = kwargs.get('enable_ooo', False)
        self.ooo_config = kwargs.get('ooo_config', {
            'mode': 'random',                # 'random' or 'deterministic'
            'reorder_probability': 0.3,      # Probability to delay a transaction
            'min_delay_cycles': 1,           # Minimum delay before response
            'max_delay_cycles': 50,          # Maximum delay before response
            'pattern': None,                 # For deterministic mode: [sequence_order]
        })

        # OOO state tracking (AXI4 compliant: same ID must stay in order)
        self.ooo_transaction_sequence = 0    # Global transaction counter
        self.ooo_transaction_metadata = {}   # {txn_seq: {'id': id, 'addr': addr}}
        self.ooo_last_completed_seq = {}     # {id: last_completed_sequence}

        # In-order mode serialization: ensure same-ID transactions complete serially
        self.in_order_active = {}            # {id: bool} - track if ID is actively responding
        self.in_order_queue = {}             # {id: [ar_packets]} - queue of waiting requests per ID

        # Fields the DUT genuinely does not carry (e.g. AxREGION on an AXI5
        # port -- AMBA5 removed it). Declared fields otherwise bind fatally.
        self.optional_fields = kwargs.get('optional_fields')

        # AR Channel (Address Read) - GAXISlave drives arready and receives AR requests
        self.ar_channel = GAXISlave(
            dut=dut,
            title=f"AR_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_ar_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="ar",
            multi_sig=self.multi_sig,
            protocol_type='axi4_ar_slave',  # Use AXI4-specific patterns
            log=log,
            optional_fields=self.optional_fields,
        )

        # R Channel (Read Data + Response) - GAXIMaster drives R responses
        self.r_channel = GAXIMaster(
            dut=dut,
            title=f"R_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_r_field_config(
                self.id_width, self.data_width, self.user_width
            ),
            pkt_prefix="r",
            multi_sig=self.multi_sig,
            protocol_type='axi4_r_master',  # Use AXI4-specific patterns
            log=log,
            super_debug=True,
        )

        # CRITICAL: Set up callback from AR slave to trigger R responses
        self.ar_channel.add_callback(self._ar_callback)

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXI4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            id_width=self.id_width,
            addr_width=self.addr_width,
            user_width=self.user_width,
            multi_sig=self.multi_sig
        )

        if self.log:
            mode_str = "OOO mode ENABLED" if self.enable_ooo else "In-order mode"
            if self.enable_ooo:
                mode_str += f" (reorder_prob={self.ooo_config.get('reorder_probability', 0.3)}, " \
                        f"delay=[{self.ooo_config.get('min_delay_cycles', 1)}, " \
                        f"{self.ooo_config.get('max_delay_cycles', 50)}])"
            self.log.info(f"AXI4SlaveRead initialized: AR callback linked to R master, {mode_str}")
            if self.compliance_checker:
                self.log.info("AXI4SlaveRead: Compliance checking enabled")

    def _ar_callback(self, ar_packet):
        """
        Callback triggered when AR slave receives a packet.
        Supports both in-order and OOO response modes. Tracks sequence for AXI4 compliance.
        """
        transaction_id = getattr(ar_packet, 'id', 0)
        addr = getattr(ar_packet, 'addr', 0)

        # Assign sequence number if OOO enabled (for AXI4 same-ID ordering)
        if self.enable_ooo:
            txn_sequence = self.ooo_transaction_sequence
            self.ooo_transaction_sequence += 1
            self.ooo_transaction_metadata[txn_sequence] = {
                'id': transaction_id,
                'addr': addr
            }
            # Store sequence in packet for later retrieval
            ar_packet._ooo_sequence = txn_sequence
            seq_str = f", seq={txn_sequence}"
        else:
            seq_str = ""

        if self.log:
            self.log.debug(f"AXI4SlaveRead: AR callback triggered - "
                        f"addr=0x{addr:08X}, id={transaction_id}{seq_str}")

        # Schedule R response generation with appropriate delay
        if self.enable_ooo:
            delay_cycles = self._calculate_ooo_delay_read(ar_packet)
            if self.log:
                self.log.debug(f"AXI4SlaveRead: Scheduling OOO completion for "
                            f"txn {transaction_id} after {delay_cycles} cycles")
            cocotb.start_soon(self._generate_read_response_delayed(ar_packet, delay_cycles))
        else:
            # In-order mode: serialize responses for same ID using lock
            cocotb.start_soon(self._generate_read_response_serialized(ar_packet))

    def _calculate_ooo_delay_read(self, ar_packet):
        """
        Calculate delay cycles for OOO read response (AXI4 compliant: same ID must stay in order).

        Args:
            ar_packet: AR packet with transaction details

        Returns:
            Delay in clock cycles before sending response
        """
        # Get transaction metadata from packet
        txn_sequence = getattr(ar_packet, '_ooo_sequence', None)
        if txn_sequence is None:
            return 1  # OOO not enabled

        transaction_id = getattr(ar_packet, 'id', 0)
        txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
        txn_id = txn_meta.get('id', transaction_id)

        # AXI4 COMPLIANCE: Check if previous same-ID transactions have completed
        last_completed = self.ooo_last_completed_seq.get(txn_id, -1)

        # Find all pending same-ID transactions with lower sequence numbers
        blocking_sequences = []
        for seq, meta in self.ooo_transaction_metadata.items():
            if meta['id'] == txn_id and seq < txn_sequence and seq > last_completed:
                blocking_sequences.append(seq)

        # If there are blocking transactions, we MUST wait
        if blocking_sequences:
            if self.log:
                self.log.debug(f"AXI4SlaveRead: Transaction seq={txn_sequence} id={txn_id} "
                            f"blocked by {len(blocking_sequences)} earlier same-ID transactions")
            return 100  # Long delay to let earlier transactions complete

        mode = self.ooo_config.get('mode', 'random')

        if mode == 'deterministic':
            # Pattern specifies SEQUENCE order (not ID order!)
            pattern = self.ooo_config.get('pattern', [])
            if pattern and txn_sequence < len(pattern):
                try:
                    target_position = pattern.index(txn_sequence)
                    current_position = len([s for s in self.ooo_last_completed_seq.values() if s >= 0])

                    if target_position > current_position:
                        delay = (target_position - current_position) * 20
                    else:
                        delay = 1

                    if self.log:
                        self.log.debug(f"AXI4SlaveRead: Deterministic OOO seq={txn_sequence} "
                                    f"id={txn_id}, pattern_pos={target_position}, delay={delay}")

                    return delay
                except ValueError:
                    return self.ooo_config.get('min_delay_cycles', 1)
            else:
                return self.ooo_config.get('min_delay_cycles', 1)

        elif mode == 'random':
            # Random delay within range (same-ID ordering already enforced above)
            min_delay = self.ooo_config.get('min_delay_cycles', 1)
            max_delay = self.ooo_config.get('max_delay_cycles', 50)
            base_delay = random.randint(min_delay, max_delay)

            reorder_prob = self.ooo_config.get('reorder_probability', 0.3)
            if random.random() < reorder_prob:
                extra_delay = random.randint(20, 50)
                return base_delay + extra_delay
            else:
                return base_delay

        else:
            return 1

    async def _generate_read_response_serialized(self, ar_packet):
        """
        Generate read response with serialization for in-order mode (enable_ooo=False).
        Ensures that all responses for the same ID complete serially using queue-based serialization.

        Args:
            ar_packet: AR packet with transaction details

        Synchronization note (issue #13 audit):
            No `cocotb.triggers.Lock` is needed around the queue/active mutations
            below. The check-then-set on `in_order_active[id]` (read at line marked
            'active check', write at 'active set') and the queue append/pop happen
            between awaits within this coroutine. Cocotb's cooperative scheduler
            runs each coroutine until its next `await`, so no other coroutine
            observes a half-mutated state. The first await is `_generate_read_response`
            below; everything above it is atomic w.r.t. other coroutines.
            This is structurally different from the across-await race that motivated
            `completion_locks` on the slave-write side — do not "fix" by adding a lock.
            If you ever introduce an `await` between the queue append and the active
            check/set, you MUST add a per-ID Lock to keep the section atomic.
        """
        transaction_id = getattr(ar_packet, 'id', 0)

        # Initialize queue and active flag for this ID if needed
        if transaction_id not in self.in_order_queue:
            self.in_order_queue[transaction_id] = []
            self.in_order_active[transaction_id] = False

        # Add packet to queue (atomic — no await)
        self.in_order_queue[transaction_id].append(ar_packet)

        # active check + early return: atomic — no await between this and the
        # 'active set' below; safe under cocotb cooperative scheduling.
        if self.in_order_active[transaction_id]:
            if self.log:
                self.log.debug(f"AXI4SlaveRead: Queued request for id={transaction_id} "
                            f"(queue_len={len(self.in_order_queue[transaction_id])})")
            return

        # Mark this ID as active (atomic 'active set' — see synchronization note in docstring)
        self.in_order_active[transaction_id] = True

        # Process all queued packets for this ID serially
        while self.in_order_queue[transaction_id]:
            packet = self.in_order_queue[transaction_id].pop(0)

            if self.log:
                self.log.debug(f"AXI4SlaveRead: Starting serialized response for id={transaction_id} "
                            f"(remaining={len(self.in_order_queue[transaction_id])})")

            # Generate response
            await self._generate_read_response(packet)

            if self.log:
                self.log.debug(f"AXI4SlaveRead: Completed serialized response for id={transaction_id}")

        # Mark this ID as no longer active
        self.in_order_active[transaction_id] = False

    async def _generate_read_response_delayed(self, ar_packet, delay_cycles):
        """
        Generate read response after specified delay (for OOO mode).

        Args:
            ar_packet: AR packet with transaction details
            delay_cycles: Number of clock cycles to wait before completion
        """
        # Wait for specified delay
        for _ in range(delay_cycles):
            await RisingEdge(self.clock)

        transaction_id = getattr(ar_packet, 'id', 0)
        if self.log:
            self.log.debug(f"AXI4SlaveRead: OOO delay complete for txn {transaction_id}, sending R response")

        # Now generate the response normally
        await self._generate_read_response(ar_packet)

    async def _generate_read_response(self, ar_packet):
        """Generate R response for an AR request using generic field names. UNCHANGED."""
        try:
            # Extract AR packet fields using GENERIC field names
            address = getattr(ar_packet, 'addr', 0)
            burst_len = getattr(ar_packet, 'len', 0) + 1
            packet_id = getattr(ar_packet, 'id', 0)
            size_encoding = getattr(ar_packet, 'size', 2)
            bytes_per_beat = 1 << size_encoding

            if self.log:
                self.log.debug(f"AXI4SlaveRead: Generating {burst_len} beat response for "
                            f"addr=0x{address:08X}, id={packet_id}")

            # Add configurable delay
            for _ in range(self.response_delay_cycles):
                await RisingEdge(self.clock)

            # Generate response data beats
            # PERFORMANCE FIX: Generate all beats synchronously, queue directly to transmit_queue,
            # then trigger pipeline once at end. This eliminates per-beat async overhead.
            r_packets = []
            for i in range(burst_len):
                current_addr = address + (i * bytes_per_beat)

                # Read from memory model if available
                if self.memory_model:
                    try:
                        # Apply base address offset before accessing memory model
                        # (RTL sends absolute addresses, memory model expects 0-based offsets)
                        memory_offset = current_addr - self.base_addr

                        # Read bytes from memory model
                        data_bytes = self.memory_model.read(memory_offset, bytes_per_beat)
                        # Convert to integer using memory model's utility
                        data = self.memory_model.bytearray_to_integer(data_bytes)

                        if self.log:
                            self.log.debug(f"AXI4SlaveRead: Read from memory - "
                                        f"addr=0x{current_addr:08X}, data=0x{data:08X}")
                    except Exception as e:
                        if self.log:
                            self.log.warning(f"Memory read failed at 0x{current_addr:08X}: {e}")
                        data = current_addr  # Fallback pattern
                else:
                    # Simple address-based pattern for testing
                    data = current_addr

                # Create R response packet using GENERIC field names
                is_last = (i == burst_len - 1)
                beat_resp = 0
                if self.resp_override is not None:
                    forced = self.resp_override(current_addr)
                    if forced is not None:
                        beat_resp = forced
                r_packet = self.r_channel.create_packet(
                    id=packet_id,
                    data=data,
                    resp=beat_resp,
                    last=1 if is_last else 0
                )

                r_packets.append(r_packet)

            # PERFORMANCE: Add all beats to queue synchronously (no per-beat await overhead)
            # This keeps the queue full and prevents the pipeline from going idle
            for r_packet in r_packets:
                self.r_channel.transmit_queue.append(r_packet)

            if self.log:
                self.log.debug(f"AXI4SlaveRead: Queued {len(r_packets)} beats for burst (id={packet_id})")

            # Start pipeline if not already running
            # Note: if pipeline is already active, it will process the newly queued beats
            if not self.r_channel.transmit_coroutine:
                if self.log:
                    self.log.debug(f"AXI4SlaveRead: Starting transmit pipeline for id={packet_id}")
                self.r_channel.transmit_coroutine = cocotb.start_soon(self.r_channel._transmit_pipeline())

            # Update OOO tracking: mark this transaction as completed after all beats sent
            if self.enable_ooo:
                txn_sequence = getattr(ar_packet, '_ooo_sequence', None)
                if txn_sequence is not None:
                    txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
                    txn_id = txn_meta.get('id', packet_id)
                    # Record this as the last completed sequence for this ID
                    self.ooo_last_completed_seq[txn_id] = txn_sequence
                    if self.log:
                        self.log.debug(f"AXI4SlaveRead: Marked txn seq={txn_sequence} "
                                    f"(id={txn_id}) as completed")

        except Exception as e:
            if self.log:
                self.log.error(f"AXI4SlaveRead: Error generating response: {e}")

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """
        ENHANCEMENT: Get compliance report if compliance checking is enabled.

        Returns:
            Compliance report dictionary or None if compliance checking disabled
        """
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """ENHANCEMENT: Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXI4SlaveRead: Compliance checking is disabled")


class AXI4SlaveWrite:
    """
    AXI4 Slave Write Interface - Enhanced with integrated compliance checking.

    Properly handles AXI4 specification requirement that W data can arrive before AW address.
    Uses GAXISlave for AW/W (drives ready signals) with callback to GAXIMaster for B (drives responses).

    ENHANCEMENT: Automatically includes compliance checking when enabled via environment.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI4 Slave Write interface with compliance checking."""
        self.super_debug = kwargs.get('super_debug', False)
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        # Extract configuration parameters
        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)  # AXI4 uses individual signals by default

        # Store memory model if provided
        self.memory_model = kwargs.get('memory_model')

        # Base address offset (for memory-mapped slaves)
        # If provided, incoming AXI addresses will have base_addr subtracted
        # before accessing memory_model (which expects 0-based offsets)
        self.base_addr = kwargs.get('base_addr', 0)

        # Response configuration
        self.response_delay_cycles = kwargs.get('response_delay', 1)

        # Out-of-order response configuration
        self.enable_ooo = kwargs.get('enable_ooo', False)
        self.ooo_config = kwargs.get('ooo_config', {
            'mode': 'random',                # 'random' or 'deterministic'
            'reorder_probability': 0.3,      # Probability to delay a transaction
            'min_delay_cycles': 1,           # Minimum delay before response
            'max_delay_cycles': 50,          # Maximum delay before response
            'pattern': None,                 # For deterministic mode: [sequence_order]
        })

        # OOO state tracking (AXI4 compliant: same ID must stay in order)
        self.ooo_transaction_sequence = 0    # Global transaction counter
        self.ooo_transaction_metadata = {}   # {txn_seq: {'id': id, 'addr': addr}}
        self.ooo_last_completed_seq = {}     # {id: last_completed_sequence}

        # Fields the DUT genuinely does not carry (e.g. AxREGION on an AXI5
        # port -- AMBA5 removed it). Declared fields otherwise bind fatally.
        self.optional_fields = kwargs.get('optional_fields')

        # AW Channel - GAXISlave drives awready and receives AW requests
        self.aw_channel = GAXISlave(
            dut=dut,
            title=f"AW_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_aw_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="aw",
            multi_sig=self.multi_sig,
            protocol_type='axi4_aw_slave',  # Use AXI4-specific patterns
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        # W Channel - GAXISlave drives wready and receives W data
        self.w_channel = GAXISlave(
            dut=dut,
            title=f"W_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_w_field_config(
                self.data_width, self.user_width
            ),
            pkt_prefix="w",
            multi_sig=self.multi_sig,
            protocol_type='axi4_w_slave',  # Use AXI4-specific patterns
            super_debug=self.super_debug,
            log=log,
        )

        # B Channel - GAXIMaster drives B responses
        self.b_channel = GAXIMaster(
            dut=dut,
            title=f"B_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI4FieldConfigHelper.create_b_field_config(
                self.id_width, self.user_width
            ),
            pkt_prefix="b",
            multi_sig=self.multi_sig,
            protocol_type='axi4_b_master',  # Use AXI4-specific patterns
            super_debug=self.super_debug,
            log=log,
        )

        # Set up callbacks
        self.aw_channel.add_callback(self._aw_callback)
        self.w_channel.add_callback(self._w_callback)

        # AXI4-compliant transaction tracking
        # id -> list of transactions (to handle multiple outstanding transactions with same ID)
        # Each transaction: {aw_packet: ..., w_packets: [...], complete: bool, expected_beats: ...}
        #
        # Synchronization invariant (issue #14 audit):
        #   - pending_transactions, orphaned_w_packets, w_transaction_queue are
        #     mutated from THREE call paths:
        #       1. _aw_callback (SYNC def — invoked by GAXISlave's monitor coro
        #          between its awaits)
        #       2. _w_callback  (SYNC def — same)
        #       3. _complete_write_transaction (async, but mutations of
        #          pending_transactions[id] happen either inside the per-ID
        #          completion_locks[id] guard, or in the `finally` cleanup
        #          which uses list.remove (atomic between awaits)).
        #   - Callbacks 1 and 2 MUST remain `def` (not `async def`). If they
        #     ever gain an `await`, the dict mutations they perform are no
        #     longer atomic w.r.t. other coroutines, and the AW+W matching
        #     state becomes racy. Mark with a comment if you ever need to
        #     restructure.
        #   - No additional locks are needed today; this is documented to
        #     prevent future regressions.
        self.pending_transactions = {}  # id -> [transaction_list] (FIFO order)

        # AXI4-compliant W-before-AW buffering (see synchronization invariant above)
        self.orphaned_w_packets = []    # W packets that arrived before corresponding AW
        self.w_transaction_queue = []   # Queue of complete W burst sequences

        # Per-ID locks: serialize the "find an uncompleted txn in the list and
        # mark it completing" critical section in _complete_write_transaction.
        # cocotb.triggers.Lock (not asyncio.Lock) — see commit 9d6cbc9.
        self.completion_locks = {}      # id -> cocotb.triggers.Lock

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXI4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            id_width=self.id_width,
            addr_width=self.addr_width,
            user_width=self.user_width,
            multi_sig=self.multi_sig
        )

        if self.log:
            mode_str = "OOO mode ENABLED" if self.enable_ooo else "In-order mode"
            if self.enable_ooo:
                mode_str += f" (reorder_prob={self.ooo_config.get('reorder_probability', 0.3)}, " \
                        f"delay=[{self.ooo_config.get('min_delay_cycles', 1)}, " \
                        f"{self.ooo_config.get('max_delay_cycles', 50)}])"
            self.log.info(f"AXI4SlaveWrite initialized: AW/W callbacks linked to B master with W-before-AW support, {mode_str}")
            if self.compliance_checker:
                self.log.info("AXI4SlaveWrite: Compliance checking enabled")

    def _aw_callback(self, aw_packet):
        """Handle AW packet reception using generic field names. Tracks sequence for AXI4-compliant OOO.

        MUST remain sync (`def`, not `async def`). Mutates shared state
        (pending_transactions, orphaned_w_packets via _match_orphaned_w_packets);
        sync invocation is what keeps those mutations atomic under cocotb's
        cooperative scheduler. See synchronization invariant in __init__.
        """
        transaction_id = getattr(aw_packet, 'id', 0)
        burst_len = getattr(aw_packet, 'len', 0) + 1
        addr = getattr(aw_packet, 'addr', 0)

        # Assign sequence number for tracking arrival order
        # In FIFO mode: sequence tracks global AW order across all IDs
        # In OOO mode: sequence used for same-ID ordering enforcement
        txn_sequence = self.ooo_transaction_sequence
        self.ooo_transaction_sequence += 1
        if self.enable_ooo:
            self.ooo_transaction_metadata[txn_sequence] = {
                'id': transaction_id,
                'addr': addr
            }

        # AXI4-compliant: Allow multiple transactions with same ID (must complete in-order)
        if transaction_id not in self.pending_transactions:
            self.pending_transactions[transaction_id] = []  # Initialize list for this ID

        # Append new transaction to list (FIFO order)
        self.pending_transactions[transaction_id].append({
            'aw_packet': aw_packet,
            'w_packets': [],
            'expected_beats': burst_len,
            'complete': False,
            'sequence': txn_sequence  # For OOO tracking
        })

        if self.log:
            seq_str = f", seq={txn_sequence}" if self.enable_ooo else ""
            self.log.debug(f"AXI4SlaveWrite: AW received - id={transaction_id}, "
                        f"addr=0x{addr:08X}, expected_beats={burst_len}{seq_str}")

        # AXI4-compliant: Check if we have orphaned W packets that can now be matched
        self._match_orphaned_w_packets()

    def _w_callback(self, w_packet):
        """Handle W packet reception - AXI4 compliant W-before-AW handling.

        MUST remain sync (`def`, not `async def`). Same rationale as
        _aw_callback: sync invocation is what keeps mutations of
        pending_transactions / orphaned_w_packets / w_transaction_queue atomic
        w.r.t. other coroutines. See synchronization invariant in __init__.
        """
        is_last = getattr(w_packet, 'last', 0)
        data_val = getattr(w_packet, 'data', 0)

        if self.log:
            self.log.debug(f"AXI4SlaveWrite: W received - data=0x{data_val:08X}, last={is_last}")

        # AXI4-compliant: Handle W-before-AW case
        if not self.pending_transactions:
            if self.log:
                self.log.debug("AXI4SlaveWrite: W arrived before AW - buffering (AXI4 compliant)")
            self.orphaned_w_packets.append(w_packet)

            # If this is a complete burst (last=1), queue it for later matching
            if is_last:
                # Move all orphaned W packets to transaction queue
                self.w_transaction_queue.append(self.orphaned_w_packets.copy())
                self.orphaned_w_packets.clear()
                if self.log:
                    self.log.debug(f"AXI4SlaveWrite: Complete W burst queued ({len(self.w_transaction_queue[-1])} beats)")
            return

        # Normal case: Match W to existing AW transaction
        # In OOO mode, match based on which transaction is expecting data
        # In FIFO mode, match to first incomplete transaction for this ID

        if self.enable_ooo:
            # OOO mode: Find transaction that needs this W packet
            transaction_id = self._find_matching_transaction_ooo()
        else:
            # FIFO mode: Find transaction with lowest sequence number (oldest AW)
            # W beats must arrive in same order as AW transactions in FIFO mode
            transaction_id = None
            min_sequence = None
            for tid in self.pending_transactions:
                for txn in self.pending_transactions[tid]:
                    if not txn['complete']:
                        txn_seq = txn.get('sequence', float('inf'))
                        if min_sequence is None or txn_seq < min_sequence:
                            min_sequence = txn_seq
                            transaction_id = tid
                        break  # Only check first incomplete txn per ID

        # Bug fix: pending_transactions is non-empty but contains only
        # complete-pending-cleanup entries (their completion tasks haven't
        # yet removed them from the list, and the next AW hasn't arrived
        # under stalled awready). Without this branch, the FIFO matching
        # below silently drops the W beat. Treat it as orphaned so
        # _match_orphaned_w_packets picks it up when the next AW lands.
        if transaction_id is None and self.pending_transactions:
            if self.log:
                self.log.debug(
                    "AXI4SlaveWrite: pending list has only complete-"
                    "pending-cleanup txns (keys=%s); routing W to orphan "
                    "path for next AW",
                    list(self.pending_transactions.keys()),
                )
            self.orphaned_w_packets.append(w_packet)
            if is_last:
                self.w_transaction_queue.append(
                    self.orphaned_w_packets.copy())
                self.orphaned_w_packets.clear()
            return

        # Debug: Log when W packet arrives but no transaction available
        if transaction_id is None and self.log:
            self.log.warning(f"AXI4SlaveWrite: W packet arrived but no pending transactions! "
                           f"pending_keys={list(self.pending_transactions.keys())}")

        if transaction_id is not None and transaction_id in self.pending_transactions:
            # Find first incomplete transaction in the list for this ID
            transaction_list = self.pending_transactions[transaction_id]
            transaction = None
            for txn in transaction_list:
                if not txn['complete']:
                    transaction = txn
                    break

            if transaction is None:
                if self.log:
                    self.log.warning(f"AXI4SlaveWrite: No incomplete transaction found for id={transaction_id}")
                return

            # Add W packet to this transaction
            transaction['w_packets'].append(w_packet)

            if self.log:
                self.log.debug(f"AXI4SlaveWrite: W matched to txn_id={transaction_id}")

            # Check if transaction is complete: MUST check both beat count AND last flag
            # AXI4 spec: Transaction complete when last=1 received on W channel
            if is_last or len(transaction['w_packets']) >= transaction['expected_beats']:
                transaction['complete'] = True
                if self.log:
                    self.log.debug(f"AXI4SlaveWrite: Transaction {transaction_id} complete")

                # Schedule completion with appropriate delay
                if self.enable_ooo:
                    delay_cycles = self._calculate_ooo_delay(transaction_id)
                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Scheduling OOO completion for "
                                    f"txn {transaction_id} after {delay_cycles} cycles")
                    cocotb.start_soon(self._complete_write_transaction_delayed(
                        transaction_id, delay_cycles))
                else:
                    # FIFO mode: immediate completion
                    cocotb.start_soon(self._complete_write_transaction(transaction_id))

    def _match_orphaned_w_packets(self):
        """Match orphaned W packets to newly arrived AW transactions.

        Called synchronously from _aw_callback (which is itself sync). Inherits
        the same "must not await" invariant — see _aw_callback / __init__.
        """
        # BUGFIX: Also check for partial orphaned W packets, not just complete bursts
        if not self.w_transaction_queue and not self.orphaned_w_packets:
            return

        # Try to match queued W bursts to pending AW transactions
        matched_any = False

        for aw_id, aw_transaction_list in self.pending_transactions.items():
            # Find first incomplete transaction in the list
            for aw_transaction in aw_transaction_list:
                if aw_transaction['complete']:
                    continue

                # BUGFIX: First check if we have a complete queued burst
                if self.w_transaction_queue:
                    # Match the first queued W burst to this AW
                    w_burst = self.w_transaction_queue.pop(0)
                    aw_transaction['w_packets'] = w_burst
                    aw_transaction['complete'] = True
                    matched_any = True

                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Matched orphaned W burst ({len(w_burst)} beats) to AW id={aw_id}")

                    # Complete the transaction
                    cocotb.start_soon(self._complete_write_transaction(aw_id))
                    break
                # BUGFIX: If no complete burst, but we have partial orphaned W packets,
                # transfer them to this AW transaction so they can receive the remaining W beats
                elif self.orphaned_w_packets:
                    aw_transaction['w_packets'] = self.orphaned_w_packets.copy()
                    self.orphaned_w_packets.clear()
                    matched_any = True

                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Matched {len(aw_transaction['w_packets'])} partial orphaned W packets to AW id={aw_id}, "
                                     f"expecting {aw_transaction['expected_beats']} total beats")
                    # Don't mark as complete - more W beats will arrive
                    # Don't call _complete_write_transaction yet
                    break

            if matched_any:
                break

        if matched_any and self.log:
            self.log.debug(f"AXI4SlaveWrite: W-before-AW matching complete, remaining queued bursts: {len(self.w_transaction_queue)}, "
                         f"remaining orphaned packets: {len(self.orphaned_w_packets)}")

    def _find_matching_transaction_ooo(self):
        """
        Find which transaction should receive the next W packet in OOO mode.

        Strategy:
        - Find incomplete transactions (have AW, need more W beats)
        - Return lowest transaction ID that needs data
        - This allows W data to arrive in any order

        Returns:
            transaction_id or None if no match
        """
        for txn_id in sorted(self.pending_transactions.keys()):
            txn_list = self.pending_transactions[txn_id]
            # Check all transactions in the list for this ID
            for txn in txn_list:
                if len(txn['w_packets']) < txn['expected_beats']:
                    # This transaction needs more W beats
                    return txn_id
        return None

    def _calculate_ooo_delay(self, transaction_id):
        """
        Calculate delay cycles for OOO response (AXI4 compliant: same ID must stay in order).

        Modes:
        - 'deterministic': Use pattern[sequence] to determine completion order
        - 'random': Random delay, but respects same-ID ordering

        Args:
            transaction_id: Transaction ID completing

        Returns:
            Delay in clock cycles before sending response
        """
        # Get transaction metadata
        if transaction_id not in self.pending_transactions:
            return 1

        # Get first transaction in the list (FIFO order)
        txn_list = self.pending_transactions[transaction_id]
        if not txn_list:
            return 1
        txn = txn_list[0]
        txn_sequence = txn.get('sequence')
        if txn_sequence is None:
            return 1  # OOO not enabled for this transaction

        # Get transaction metadata from tracking
        txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
        txn_id = txn_meta.get('id', transaction_id)

        # AXI4 COMPLIANCE: Check if previous same-ID transactions have completed
        last_completed = self.ooo_last_completed_seq.get(txn_id, -1)

        # Find all pending same-ID transactions with lower sequence numbers
        blocking_sequences = []
        for seq, meta in self.ooo_transaction_metadata.items():
            if meta['id'] == txn_id and seq < txn_sequence and seq > last_completed:
                blocking_sequences.append(seq)

        # If there are blocking transactions, we MUST wait
        if blocking_sequences:
            if self.log:
                self.log.debug(f"AXI4SlaveWrite: Transaction seq={txn_sequence} id={txn_id} "
                            f"blocked by {len(blocking_sequences)} earlier same-ID transactions")
            # Add large delay to ensure earlier same-ID transactions complete first
            # This will be checked again when this transaction is retried
            return 100  # Long delay to let earlier transactions complete

        mode = self.ooo_config.get('mode', 'random')

        if mode == 'deterministic':
            # Pattern specifies SEQUENCE order (not ID order!)
            pattern = self.ooo_config.get('pattern', [])
            if pattern and txn_sequence < len(pattern):
                # Pattern[i] tells us which sequence number should complete at position i
                # Find our position in the pattern
                try:
                    target_position = pattern.index(txn_sequence)
                    current_position = len([s for s in self.ooo_last_completed_seq.values() if s >= 0])

                    # Delay based on how far ahead we are in the pattern
                    if target_position > current_position:
                        delay = (target_position - current_position) * 20
                    else:
                        delay = 1  # Ready to complete now

                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Deterministic OOO seq={txn_sequence} "
                                    f"id={txn_id}, pattern_pos={target_position}, delay={delay}")

                    return delay
                except ValueError:
                    # Sequence not in pattern, use min delay
                    return self.ooo_config.get('min_delay_cycles', 1)
            else:
                return self.ooo_config.get('min_delay_cycles', 1)

        elif mode == 'random':
            # Random delay within range (but same-ID ordering already enforced above)
            min_delay = self.ooo_config.get('min_delay_cycles', 1)
            max_delay = self.ooo_config.get('max_delay_cycles', 50)
            base_delay = random.randint(min_delay, max_delay)

            # With reorder probability, add extra delay
            # This causes reordering BETWEEN different IDs, not within same ID
            reorder_prob = self.ooo_config.get('reorder_probability', 0.3)
            if random.random() < reorder_prob:
                extra_delay = random.randint(20, 50)
                return base_delay + extra_delay
            else:
                return base_delay

        else:
            # Unknown mode, use default
            return 1

    async def _complete_write_transaction_delayed(self, transaction_id, delay_cycles):
        """
        Complete write transaction after specified delay (for OOO mode).

        Args:
            transaction_id: ID of transaction to complete
            delay_cycles: Number of clock cycles to wait before completion
        """
        # Wait for specified delay
        for _ in range(delay_cycles):
            await RisingEdge(self.clock)

        if self.log:
            self.log.debug(f"AXI4SlaveWrite: OOO delay complete for txn {transaction_id}, sending B response")

        # Now complete the transaction normally
        await self._complete_write_transaction(transaction_id)

    async def _complete_write_transaction(self, transaction_id):
            """Complete write transaction and send B response using generic field names."""
            # Per-ID lock to make the "check pending_transactions then send B"
            # sequence atomic against concurrent completion attempts for the
            # same ID (which can happen when overlapping bursts share IDs).
            # cocotb.triggers.Lock — NOT asyncio.Lock — because cocotb's
            # scheduler is not an asyncio loop; asyncio.Lock().acquire()
            # crashes on first contended use ('NoneType has no attribute
            # create_future'). Same fix landed for the master-side BFMs in
            # commit e5ebf7b.
            if transaction_id not in self.completion_locks:
                self.completion_locks[transaction_id] = Lock(
                    name=f"AXI4SlaveWrite_completion_id{transaction_id}")

            # Use lock to ensure atomic check-and-set of completing flag
            async with self.completion_locks[transaction_id]:
                # Prevent race condition - check if transaction still exists
                if transaction_id not in self.pending_transactions:
                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Transaction {transaction_id} already completed - skipping")
                    return

                # Get the transaction list for this ID
                transaction_list = self.pending_transactions[transaction_id]
                if not transaction_list:
                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Transaction list for {transaction_id} is empty - skipping")
                    return

                # Get first complete transaction that's not already completing (FIFO order)
                transaction = None
                for txn in transaction_list:
                    if txn['complete'] and not txn.get('completing', False):
                        transaction = txn
                        break

                if transaction is None:
                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: No uncompleted transaction found for {transaction_id} - skipping")
                    return

                # Mark as completing to prevent race condition
                # This is now atomic because we're inside the lock
                transaction['completing'] = True

            # Update OOO tracking: mark this transaction as completed
            if self.enable_ooo:
                txn_sequence = transaction.get('sequence')
                if txn_sequence is not None:
                    txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
                    txn_id = txn_meta.get('id', transaction_id)
                    # Record this as the last completed sequence for this ID
                    self.ooo_last_completed_seq[txn_id] = txn_sequence
                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Completed seq={txn_sequence} id={txn_id}")

            aw_packet = transaction['aw_packet']
            w_packets = transaction['w_packets']

            try:
                # Extract address info using generic field names
                base_addr = getattr(aw_packet, 'addr', 0)
                size_encoding = getattr(aw_packet, 'size', 2)
                bytes_per_beat = 1 << size_encoding

                # Write data to memory if available
                if self.memory_model:
                    # W data and WSTRB are bus-width quantities: a narrow
                    # beat (AWSIZE < bus width) rides in its addressed byte
                    # lanes with only those strobes set. Writing the full
                    # bus word at the bus-aligned address with the wire
                    # strobe handles narrow and full beats identically.
                    # (The old code sliced the data down to 1<<AWSIZE bytes
                    # but kept the bus-width strobe -- memory_model.write
                    # rejected the mismatch and the write was dropped.)
                    bus_bytes = self.data_width // 8
                    for i, w_packet in enumerate(w_packets):
                        addr = base_addr + (i * bytes_per_beat)
                        bus_aligned_addr = addr - (addr % bus_bytes)

                        # Apply base address offset before accessing memory model
                        # (RTL sends absolute addresses, memory model expects 0-based offsets)
                        memory_offset = bus_aligned_addr - self.base_addr

                        data = getattr(w_packet, 'data', 0)
                        strb = getattr(w_packet, 'strb', (1 << bus_bytes) - 1)

                        # Convert data to proper bytearray format
                        try:
                            data_bytes = self.memory_model.integer_to_bytearray(data, bus_bytes)
                            self.memory_model.write(memory_offset, data_bytes, strb)
                        except Exception as mem_error:
                            if self.log:
                                self.log.warning(f"AXI4SlaveWrite: Memory write failed for txn {transaction_id}: {mem_error}")

                # Add delay for realistic B response timing
                if self.response_delay_cycles > 0:
                    for _ in range(self.response_delay_cycles):
                        await RisingEdge(self.clock)

                # Double-check transaction still exists before sending B response
                if transaction_id not in self.pending_transactions:
                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Transaction {transaction_id} was deleted during completion")
                    return

                # Send B response using generic field names
                b_packet = self.b_channel.create_packet(
                    id=transaction_id,
                    resp=0
                )

                await self.b_channel.send(b_packet)

                if self.log:
                    self.log.debug(f"AXI4SlaveWrite: B response sent - id={transaction_id}, "
                                f"addr=0x{base_addr:08X}, beats={len(w_packets)}")

            except Exception as e:
                if self.log:
                    self.log.error(f"AXI4SlaveWrite: Error completing transaction {transaction_id}: {e}")
            finally:
                # Safe cleanup - remove completed transaction from list
                if transaction_id in self.pending_transactions:
                    transaction_list = self.pending_transactions[transaction_id]
                    # Remove the completed transaction from the list
                    if transaction in transaction_list:
                        transaction_list.remove(transaction)
                        if self.log:
                            self.log.debug(f"AXI4SlaveWrite: Transaction {transaction_id} removed from list "
                                        f"({len(transaction_list)} remaining)")

                    # If list is now empty, remove the ID entry
                    if not transaction_list:
                        del self.pending_transactions[transaction_id]
                        if self.log:
                            self.log.debug(f"AXI4SlaveWrite: All transactions for ID {transaction_id} completed")
                else:
                    if self.log:
                        self.log.debug(f"AXI4SlaveWrite: Transaction {transaction_id} was already cleaned up")

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """
        ENHANCEMENT: Get compliance report if compliance checking is enabled.

        Returns:
            Compliance report dictionary or None if compliance checking disabled
        """
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """ENHANCEMENT: Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXI4SlaveWrite: Compliance checking is disabled")

# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL4MasterRead
# Purpose: AXIL4 Interface Classes - COMPLETE UPDATED FILE
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXIL4 Interface Classes - COMPLETE UPDATED FILE

CHANGES:
1. ✅ SIMPLIFIED: Removed all user signal support (not in AXIL4 spec)
2. ✅ API CONSISTENCY: Added single_read/write and read/write_register methods
3. ✅ COMPLIANCE: Integrated automatic compliance checking
4. ✅ BACKWARD COMPATIBLE: All existing methods preserved

This file is ready to replace the existing axil4_interfaces.py
"""

import collections
from typing import Any, Dict, Optional

import cocotb
from cocotb.triggers import Event, Lock, RisingEdge

from CocoTBFramework.components.axil4.axil4_compliance_checker import AXIL4ComplianceChecker
from CocoTBFramework.components.axil4.axil4_field_configs import AXIL4FieldConfigHelper
from CocoTBFramework.components.axil4.axil4_packet import AXIL4Packet

# Import GAXI components and field configs
from CocoTBFramework.components.gaxi.gaxi_master import GAXIMaster
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave


class AXIL4MasterRead:
    """
    AXIL4 Master Read Interface - Specification compliant with perfect API consistency.

    PROVIDES IDENTICAL API TO AXI4MasterRead:
    - read_transaction() - Core transaction method
    - simple_read() - Original AXIL4 method (backward compatibility)
    - single_read() - NEW: Matches AXI4 API exactly
    - read_register() - NEW: Semantic alias for register access

    SIMPLIFIED: No user signal support (AXIL4 spec compliant)
    """

    def __init__(self, dut, clock, prefix="", log=None, **kwargs):
        """Initialize AXIL4 Master Read interface with automatic compliance checking."""
        self.clock = clock
        self.log = log

        # Extract configuration parameters (SIMPLIFIED - no user signals)
        self.data_width = kwargs.get('data_width', 32)
        self.addr_width = kwargs.get('addr_width', 32)
        self.multi_sig = kwargs.get('multi_sig', False)

        # AR Channel (Address Read) - Master drives
        self.ar_channel = GAXIMaster(
            dut=dut,
            title="AR_Master",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_ar_field_config(
                self.addr_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="ar",
            multi_sig=self.multi_sig,
            log=log
        )

        # R Channel - Slave receives R data
        self.r_channel = GAXISlave(
            dut=dut,
            title="R_Slave",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_r_field_config(
                self.data_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="r",
            multi_sig=self.multi_sig,
            log=log
        )

        # Store parameters for transaction methods
        self.timeout_cycles = kwargs.get('timeout_cycles', 1000)

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            addr_width=self.addr_width,
            multi_sig=self.multi_sig
            # SIMPLIFIED: No user_width parameter
        )

        if self.compliance_checker and log:
            log.info("AXIL4MasterRead: Compliance checking enabled")

        # Per-call response waiters for concurrent read_transaction() pickup.
        # AXIL4 has no AID/RID, so we can't key on ID like AXI4/AXI5. Instead
        # we register one (event, slot) per pending call and the callback
        # routes each arriving R into the next waiter in FIFO order (matching
        # AXIL4 channel-level semantics). Positional indexing into
        # self.r_channel._recvQ races when callers use cocotb.start_soon:
        # every coroutine snapshots initial_count=0 and reads _recvQ[0] as
        # "theirs". Mirrors the FIFO matching introduced for AXIL4SlaveWrite
        # in 2e7e825.
        self._response_waiters = collections.deque()
        self.r_channel.add_callback(self._on_r_response)

    def _on_r_response(self, pkt):
        """Route incoming R into the next pending waiter (FIFO).

        If no waiter is registered the response is unexpected -- log and
        drop (the packet still lives in _recvQ for forensic inspection)."""
        if self._response_waiters:
            evt, slot = self._response_waiters.popleft()
            slot.append(pkt)
            evt.set()
        elif self.log:
            self.log.warning("AXIL4MasterRead: R response with no pending "
                             "waiter (dropped from pickup, retained in _recvQ)")

    async def read_transaction(self, address: int, **transaction_kwargs) -> int:
        """
        High-level read transaction - always single transfer for AXIL4.

        Concurrency-safe: each call registers its own (event, slot) pair on
        self._response_waiters BEFORE issuing AR, so the next-arriving R is
        guaranteed to be routed to this caller (FIFO). Sequential callers
        behave identically: with one outstanding transaction there's exactly
        one waiter and exactly one R.
        """
        if self.log:
            self.log.debug(f"AXIL4MasterRead: Starting read transaction addr=0x{address:08X}")

        # Create AR packet using generic field names (SIMPLIFIED - no user fields)
        ar_packet = self.ar_channel.create_packet(
            addr=address,
            prot=transaction_kwargs.get('prot', 0)
            # SIMPLIFIED: No user field handling
        )

        # Register our waiter BEFORE sending AR so we can't miss a fast response
        evt = Event()
        slot = []
        waiter = (evt, slot)
        self._response_waiters.append(waiter)

        try:
            # Send read address
            await self.ar_channel.send(ar_packet)

            # Wait for our R response via event + clock-edge polling for timeout
            cycles_waited = 0
            while not slot:
                await RisingEdge(self.clock)
                cycles_waited += 1

                if cycles_waited > self.timeout_cycles:
                    # Best-effort waiter removal (may have been popped already)
                    try:
                        self._response_waiters.remove(waiter)
                    except ValueError:
                        pass
                    raise TimeoutError(
                        f"AXIL4 read timeout after {cycles_waited} cycles at address 0x{address:08X}"
                    )
        except Exception:
            # On any failure, ensure waiter is removed so a late response
            # doesn't get mis-routed to a future caller.
            try:
                self._response_waiters.remove(waiter)
            except ValueError:
                pass
            raise

        # Extract data from our routed response packet
        packet = slot[0]
        data_value = getattr(packet, 'data', 0)

        # Check for errors
        if hasattr(packet, 'resp') and packet.resp != 0:
            resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
            resp_name = resp_names.get(packet.resp, 'UNKNOWN')
            raise RuntimeError(f"AXIL4 read error: {resp_name} (0x{packet.resp:X})")

        return data_value

    async def simple_read(self, address: int, **kwargs) -> int:
        """
        Simple register read - ORIGINAL AXIL4 method.
        KEPT: For backward compatibility.
        """
        return await self.read_transaction(address, **kwargs)

    # NEW: API CONSISTENCY METHODS
    async def single_read(self, address: int, **kwargs) -> int:
        """
        API CONSISTENCY: Single register read - identical API to AXI4.
        NEW: Matches AXI4MasterRead.single_read() exactly.
        """
        return await self.read_transaction(address, **kwargs)

    async def read_register(self, address: int, **kwargs) -> int:
        """
        API CONSISTENCY: Register read - semantic alias for register access.
        NEW: Provides clear semantic meaning for register operations.
        """
        return await self.read_transaction(address, **kwargs)

    def create_ar_packet(self, **kwargs) -> AXIL4Packet:
        """Create AR packet with current configuration using generic field names."""
        return self.ar_channel.create_packet(**kwargs)

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """Get compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXIL4MasterRead: Compliance checking is disabled")


class AXIL4MasterWrite:
    """
    AXIL4 Master Write Interface - Specification compliant with perfect API consistency.

    PROVIDES IDENTICAL API TO AXI4MasterWrite:
    - write_transaction() - Core transaction method
    - simple_write() - Original AXIL4 method (backward compatibility)
    - single_write() - NEW: Matches AXI4 API exactly
    - write_register() - NEW: Semantic alias for register access

    SIMPLIFIED: No user signal support (AXIL4 spec compliant)
    """

    def __init__(self, dut, clock, prefix="", log=None, **kwargs):
        """Initialize AXIL4 Master Write interface with automatic compliance checking."""
        self.clock = clock
        self.log = log

        # Extract configuration parameters (SIMPLIFIED - no user signals)
        self.data_width = kwargs.get('data_width', 32)
        self.addr_width = kwargs.get('addr_width', 32)
        self.multi_sig = kwargs.get('multi_sig', False)

        # AW Channel (Address Write) - Master drives
        self.aw_channel = GAXIMaster(
            dut=dut,
            title="AW_Master",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_aw_field_config(
                self.addr_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="aw",
            multi_sig=self.multi_sig,
            log=log
        )

        # W Channel (Write Data) - Master drives
        self.w_channel = GAXIMaster(
            dut=dut,
            title="W_Master",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_w_field_config(
                self.data_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="w",
            multi_sig=self.multi_sig,
            log=log
        )

        # B Channel (Write Response) - Slave receives responses
        self.b_channel = GAXISlave(
            dut=dut,
            title="B_Slave",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_b_field_config(
                # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="b",
            multi_sig=self.multi_sig,
            log=log
        )

        # Store parameters
        self.timeout_cycles = kwargs.get('timeout_cycles', 1000)

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            addr_width=self.addr_width,
            multi_sig=self.multi_sig
            # SIMPLIFIED: No user_width parameter
        )

        if self.compliance_checker and log:
            log.info("AXIL4MasterWrite: Compliance checking enabled")

        # Per-call B-response waiters for concurrent write_transaction()
        # pickup. See AXIL4MasterRead.__init__ for race rationale. AXIL4 has
        # no BID so we use a FIFO waiter list keyed only on arrival order.
        self._response_waiters = collections.deque()
        self.b_channel.add_callback(self._on_b_response)

        # AW+W issuance lock. Concurrent write_transaction calls would
        # otherwise interleave AW and W on the wire in a way that defeats
        # the FIFO B pickup -- and on slaves that pair AW+W positionally
        # the data ends up matched to the wrong address. Lock the AW+W
        # critical section per transaction. Sequential callers see an
        # uncontended lock; no behavior change. cocotb.triggers.Lock (not
        # asyncio.Lock) -- cocotb's scheduler is not asyncio.
        self._aw_w_lock = Lock(name="AXIL4MasterWrite_AW_W_Lock")

    def _on_b_response(self, pkt):
        """Route incoming B into the next pending waiter (FIFO)."""
        if self._response_waiters:
            evt, slot = self._response_waiters.popleft()
            slot.append(pkt)
            evt.set()
        elif self.log:
            self.log.warning("AXIL4MasterWrite: B response with no pending "
                             "waiter (dropped from pickup, retained in _recvQ)")

    async def write_transaction(self, address: int, data: int, strb: Optional[int] = None,
                              **transaction_kwargs) -> int:
        """
        High-level write transaction - always single transfer for AXIL4.
        STANDARDIZED: Returns response code (int) for API consistency.
        """
        if self.log:
            self.log.debug(f"AXIL4MasterWrite: Starting write transaction addr=0x{address:08X}, data=0x{data:08X}")

        # Calculate default strobe if not provided
        if strb is None:
            strb_width = self.data_width // 8
            strb = (1 << strb_width) - 1

        # Create AW and W packets (SIMPLIFIED - no user fields)
        aw_packet = self.aw_channel.create_packet(
            addr=address,
            prot=transaction_kwargs.get('prot', 0)
            # SIMPLIFIED: No user field handling
        )

        w_packet = self.w_channel.create_packet(
            data=data,
            strb=strb
            # SIMPLIFIED: No user field handling
        )

        # Serialize AW+W issuance AND waiter registration so concurrent calls
        # have the same waiter-registration order as wire-issuance order.
        # The lock guarantees no two callers interleave their (register,
        # send AW, send W) sequence -- the FIFO B-pickup then matches the
        # FIFO AW issuance.
        async with self._aw_w_lock:
            # Register our B waiter BEFORE sending AW/W (see read_transaction
            # rationale -- guarantees we can't miss a fast response).
            evt = Event()
            slot = []
            waiter = (evt, slot)
            self._response_waiters.append(waiter)

            try:
                # Send AW and W (can be concurrent in AXIL4)
                await self.aw_channel.send(aw_packet)
                await self.w_channel.send(w_packet)
            except Exception:
                try:
                    self._response_waiters.remove(waiter)
                except ValueError:
                    pass
                raise

        try:
            # Wait for our B response via event + clock-edge polling for timeout
            cycles_waited = 0
            while not slot:
                await RisingEdge(self.clock)
                cycles_waited += 1

                if cycles_waited > self.timeout_cycles:
                    try:
                        self._response_waiters.remove(waiter)
                    except ValueError:
                        pass
                    raise TimeoutError(
                        f"AXIL4 write timeout after {cycles_waited} cycles at address 0x{address:08X}"
                    )
        except Exception:
            try:
                self._response_waiters.remove(waiter)
            except ValueError:
                pass
            raise

        # Get our routed B response packet
        b_response = slot[0]
        resp_code = getattr(b_response, 'resp', 0)

        # Check for errors
        if resp_code != 0:
            resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
            resp_name = resp_names.get(resp_code, 'UNKNOWN')
            raise RuntimeError(f"AXIL4 write error: {resp_name} (0x{resp_code:X})")

        return resp_code

    async def simple_write(self, address: int, data: int, strb: Optional[int] = None, **kwargs) -> int:
        """
        Simple register write - ORIGINAL AXIL4 method.
        KEPT: For backward compatibility.
        """
        return await self.write_transaction(address, data, strb, **kwargs)

    # NEW: API CONSISTENCY METHODS
    async def single_write(self, address: int, data: int, strb: Optional[int] = None, **kwargs) -> int:
        """
        API CONSISTENCY: Single register write - identical API to AXI4.
        NEW: Matches AXI4MasterWrite.single_write() exactly.
        """
        return await self.write_transaction(address, data, strb, **kwargs)

    async def write_register(self, address: int, data: int, strb: Optional[int] = None, **kwargs) -> int:
        """
        API CONSISTENCY: Register write - semantic alias for register access.
        NEW: Provides clear semantic meaning for register operations.
        """
        return await self.write_transaction(address, data, strb, **kwargs)

    def create_aw_packet(self, **kwargs) -> AXIL4Packet:
        """Create AW packet with current configuration."""
        return self.aw_channel.create_packet(**kwargs)

    def create_w_packet(self, **kwargs) -> AXIL4Packet:
        """Create W packet with current configuration."""
        return self.w_channel.create_packet(**kwargs)

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """Get compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXIL4MasterWrite: Compliance checking is disabled")


class AXIL4SlaveRead:
    """
    AXIL4 Slave Read Interface - Simplified and specification compliant.

    SIMPLIFIED: No user signal support (AXIL4 spec compliant)
    """

    def __init__(self, dut, clock, prefix="", log=None, **kwargs):
        """Initialize AXIL4 Slave Read interface."""
        self.clock = clock
        self.log = log

        # Extract configuration parameters (SIMPLIFIED)
        self.data_width = kwargs.get('data_width', 32)
        self.addr_width = kwargs.get('addr_width', 32)
        self.multi_sig = kwargs.get('multi_sig', False)

        # Store memory model if provided
        self.memory_model = kwargs.get('memory_model')

        # Base address offset (for memory-mapped slaves).
        # Mirrors AXI4SlaveRead. Incoming ARADDR is absolute (post-bridge
        # decode); subtract base_addr before indexing into memory_model
        # which expects 0-based offsets. Without this, a slave at a
        # non-zero base address overruns its sized memory and returns
        # 0xDEADDEAD/SLVERR.
        self.base_addr = kwargs.get('base_addr', 0)
        self.response_delay_cycles = kwargs.get('response_delay', 1)
        # Optional response override: a callable (address) -> resp code,
        # or None to leave the natural response alone. Without this the
        # slave can only ever answer OKAY (or SLVERR by crashing a memory
        # read), so a DUT's error path is untestable -- which is how an
        # error-masking bug reaches a converter that has a passing suite.
        self.resp_override = kwargs.get('resp_override')

        # AR Channel - GAXISlave drives arready and receives AR requests
        self.ar_channel = GAXISlave(
            dut=dut,
            title="AR_Slave",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_ar_field_config(
                self.addr_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="ar",
            multi_sig=self.multi_sig,
            log=log,
        )

        # R Channel - GAXIMaster drives R responses
        self.r_channel = GAXIMaster(
            dut=dut,
            title="R_Master",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_r_field_config(
                self.data_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="r",
            multi_sig=self.multi_sig,
            log=log,
        )

        # Set up callback from AR slave to trigger R responses
        self.ar_channel.add_callback(self._ar_callback)

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            addr_width=self.addr_width,
            multi_sig=self.multi_sig
            # SIMPLIFIED: No user_width parameter
        )

        if self.log:
            self.log.info("AXIL4SlaveRead initialized: AR callback linked to R master")
            if self.compliance_checker:
                self.log.info("AXIL4SlaveRead: Compliance checking enabled")

    def _ar_callback(self, ar_packet):
        """Callback triggered when AR slave receives a packet."""
        if self.log:
            self.log.debug(f"AXIL4SlaveRead: AR callback triggered - addr=0x{ar_packet.addr:08X}")

        # Schedule R response generation (non-blocking)
        cocotb.start_soon(self._generate_read_response(ar_packet))

    async def _generate_read_response(self, ar_packet):
        """Generate R response for an AR request using generic field names."""
        try:
            # Add response delay
            if self.response_delay_cycles > 0:
                for _ in range(self.response_delay_cycles):
                    await RisingEdge(self.clock)

            # Extract address using generic field names
            address = getattr(ar_packet, 'addr', 0)

            # Read from memory or generate data
            data = 0
            resp = 0  # OKAY

            if self.memory_model:
                try:
                    # Translate absolute AR address → 0-based memory offset.
                    memory_offset = address - self.base_addr
                    # Read bytes from memory model
                    bytes_per_transfer = self.data_width // 8
                    data_bytes = self.memory_model.read(memory_offset, bytes_per_transfer)
                    # Convert to integer using memory model's utility
                    data = self.memory_model.bytearray_to_integer(data_bytes)
                    resp = 0  # OKAY

                    if self.log:
                        self.log.debug(f"AXIL4SlaveRead: Read from memory - "
                                    f"addr=0x{address:08X} offset=0x{memory_offset:08X}, data=0x{data:08X}")
                except Exception as e:
                    if self.log:
                        self.log.warning(f"Memory read failed at 0x{address:08X} (offset 0x{address-self.base_addr:08X}): {e}")
                    data = 0xDEADDEAD
                    resp = 2  # SLVERR
            else:
                # Default data pattern
                data = (address & 0xFFFFFFFF) ^ 0xDEADBEEF

            if self.resp_override is not None:
                forced = self.resp_override(address)
                if forced is not None:
                    resp = forced

            # Create and send R response using generic field names (SIMPLIFIED)
            r_packet = self.r_channel.create_packet(
                data=data,
                resp=resp
                # SIMPLIFIED: No user field
            )

            await self.r_channel.send(r_packet)

            if self.log:
                self.log.debug(f"AXIL4SlaveRead: R response sent - data=0x{data:08X}, resp={resp}")

        except Exception as e:
            if self.log:
                self.log.error(f"AXIL4SlaveRead: Error generating R response: {e}")

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """Get compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXIL4SlaveRead: Compliance checking is disabled")


class AXIL4SlaveWrite:
    """
    AXIL4 Slave Write Interface - Simplified and specification compliant.

    SIMPLIFIED: No user signal support (AXIL4 spec compliant)
    """

    def __init__(self, dut, clock, prefix="", log=None, **kwargs):
        """Initialize AXIL4 Slave Write interface."""
        self.clock = clock
        self.log = log

        # Extract configuration parameters (SIMPLIFIED)
        self.data_width = kwargs.get('data_width', 32)
        self.addr_width = kwargs.get('addr_width', 32)
        self.multi_sig = kwargs.get('multi_sig', False)

        # Store memory model if provided
        self.memory_model = kwargs.get('memory_model')
        self.response_delay_cycles = kwargs.get('response_delay', 1)
        # Optional response override: a callable (address) -> resp code,
        # or None to leave the natural response alone. Mirrors
        # AXIL4SlaveRead; see the note there.
        self.resp_override = kwargs.get('resp_override')

        # Base address offset (mirrors AXI4SlaveWrite). Subtracted from
        # incoming absolute AWADDR before indexing into memory_model.
        self.base_addr = kwargs.get('base_addr', 0)

        # AW Channel - GAXISlave drives awready and receives AW requests
        self.aw_channel = GAXISlave(
            dut=dut,
            title="AW_Slave",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_aw_field_config(
                self.addr_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="aw",
            multi_sig=self.multi_sig,
            log=log,
        )

        # W Channel - GAXISlave drives wready and receives W data
        self.w_channel = GAXISlave(
            dut=dut,
            title="W_Slave",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_w_field_config(
                self.data_width  # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="w",
            multi_sig=self.multi_sig,
            log=log,
        )

        # B Channel - GAXIMaster drives B responses
        self.b_channel = GAXIMaster(
            dut=dut,
            title="B_Master",
            prefix=prefix,
            clock=clock,
            field_config=AXIL4FieldConfigHelper.create_b_field_config(
                # SIMPLIFIED: No user_width parameter
            ),
            pkt_prefix="b",
            multi_sig=self.multi_sig,
            log=log,
        )

        # Set up callbacks
        self.aw_channel.add_callback(self._aw_callback)
        self.w_channel.add_callback(self._w_callback)

        # Transaction tracking (simplified - no ID needed for AXIL4)
        self.pending_aw = None
        self.pending_w = None

        # ENHANCEMENT: Integrate compliance checker automatically
        self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix=prefix,
            log=log,
            data_width=self.data_width,
            addr_width=self.addr_width,
            multi_sig=self.multi_sig
            # SIMPLIFIED: No user_width parameter
        )

        if self.log:
            self.log.info("AXIL4SlaveWrite initialized: AW/W callbacks linked to B master")
            if self.compliance_checker:
                self.log.info("AXIL4SlaveWrite: Compliance checking enabled")

    def _aw_callback(self, aw_packet):
        """Handle AW packet reception.

        Single-depth pending_aw silently breaks when the upstream
        bursts get decomposed by an axi4_to_axil4_wr shim -- two AWs
        and two Ws arrive in interleaved order and the previous
        burst's residual W gets mis-matched to the new AW. Use FIFO
        queues for both sides and match strictly in arrival order
        (AXI4SlaveWrite uses the same pattern)."""
        if self.log:
            self.log.debug(f"AXIL4SlaveWrite: AW packet received - addr=0x{getattr(aw_packet, 'addr', 0):08X}")

        if not hasattr(self, '_aw_queue'):
            self._aw_queue = []
            self._w_queue = []
        self._aw_queue.append(aw_packet)
        self._try_complete_transaction()

    def _w_callback(self, w_packet):
        """Handle W packet reception. See _aw_callback for FIFO rationale."""
        if self.log:
            self.log.debug(f"AXIL4SlaveWrite: W packet received - data=0x{getattr(w_packet, 'data', 0):08X}")

        if not hasattr(self, '_aw_queue'):
            self._aw_queue = []
            self._w_queue = []
        self._w_queue.append(w_packet)
        self._try_complete_transaction()

    def _try_complete_transaction(self):
        """Match queued AWs and Ws in arrival order, drain as many
        complete pairs as available."""
        if not hasattr(self, '_aw_queue'):
            return
        while self._aw_queue and self._w_queue:
            aw_packet = self._aw_queue.pop(0)
            w_packet = self._w_queue.pop(0)
            cocotb.start_soon(self._generate_write_response(aw_packet, w_packet))

    async def _generate_write_response(self, aw_packet, w_packet):
        """Generate B response for completed write transaction using generic field names."""
        try:
            # Add response delay
            if self.response_delay_cycles > 0:
                for _ in range(self.response_delay_cycles):
                    await RisingEdge(self.clock)

            # Extract data using generic field names
            address = getattr(aw_packet, 'addr', 0)
            data = getattr(w_packet, 'data', 0)
            strb = getattr(w_packet, 'strb', 0xF)

            # Write to memory
            resp = 0  # OKAY

            if self.memory_model:
                try:
                    # Translate absolute AWADDR → 0-based memory offset.
                    memory_offset = address - self.base_addr
                    # Apply write strobes
                    data_bytes = self.data_width // 8

                    # Write individual bytes based on strobes
                    for byte_idx in range(data_bytes):
                        if strb & (1 << byte_idx):
                            byte_data = (data >> (byte_idx * 8)) & 0xFF
                            byte_addr = memory_offset + byte_idx

                            # Convert to proper bytearray format for memory model
                            data_bytearray = bytearray([byte_data])
                            self.memory_model.write(byte_addr, data_bytearray)

                    if self.log:
                        self.log.debug(f"AXIL4SlaveWrite: Wrote to memory - "
                                    f"addr=0x{address:08X} offset=0x{memory_offset:08X}, data=0x{data:08X}, strb=0x{strb:X}")
                except Exception as e:
                    if self.log:
                        self.log.warning(f"Memory write failed at 0x{address:08X}: {e}")
                    resp = 2  # SLVERR

            # Create and send B response using generic field names (SIMPLIFIED)
            if self.resp_override is not None:
                forced = self.resp_override(address)
                if forced is not None:
                    resp = forced

            b_packet = self.b_channel.create_packet(
                resp=resp
                # SIMPLIFIED: No user field
            )
            await self.b_channel.send(b_packet)

            if self.log:
                self.log.debug(f"AXIL4SlaveWrite: B response sent - resp={resp}")

        except Exception as e:
            if self.log:
                self.log.error(f"AXIL4SlaveWrite: Error generating B response: {e}")

    def get_compliance_report(self) -> Optional[Dict[str, Any]]:
        """Get compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            return self.compliance_checker.get_compliance_report()
        return None

    def print_compliance_report(self):
        """Print compliance report if compliance checking is enabled."""
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
        elif self.log:
            self.log.debug("AXIL4SlaveWrite: Compliance checking is disabled")


# Example usage and testing
if __name__ == "__main__":
    print("AXIL4 Interface Classes - COMPLETE UPDATED VERSION")
    print("=" * 60)
    print("IMPROVEMENTS:")
    print("  ✅ SIMPLIFIED: Removed all user signal support (AXIL4 spec compliant)")
    print("  ✅ API CONSISTENCY: Added single_read/write and read/write_register methods")
    print("  ✅ COMPLIANCE: Automatic compliance checking integration")
    print("  ✅ BACKWARD COMPATIBLE: All existing methods preserved")
    print("")
    print("API METHODS AVAILABLE:")
    print("  - read_transaction() / write_transaction() - Core methods")
    print("  - simple_read() / simple_write() - Original AXIL4 methods")
    print("  - single_read() / single_write() - NEW: AXI4 API compatibility")
    print("  - read_register() / write_register() - NEW: Semantic aliases")
    print("")
    print("SPECIFICATION COMPLIANCE:")
    print("  - Only AXIL4-specified signals included")
    print("  - No user signals (not in AXIL4 spec)")
    print("  - Minimal, register-oriented design")
    print("  - Perfect for embedded register interfaces")
    print("")
    print("PERFECT API CONSISTENCY WITH AXI4 ACHIEVED! 🎉")

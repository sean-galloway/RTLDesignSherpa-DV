# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI3 Interfaces
# Purpose: AXI3 Interface Classes for Master and Slave Read/Write operations.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""
AXI3 Interface Classes - Master and Slave Read/Write implementations.

This is a standalone protocol family (not an AXI4 subclass) that mirrors the
AXI4 interface shape but encodes the AXI3 deltas:

* AWLEN/ARLEN are 4 bits (1-16 beats per burst).
* AWLOCK/ARLOCK are 2 bits (normal / exclusive / locked).
* QoS and REGION signals do not exist.
* W carries WID, so write-data interleaving across IDs is legal.

The AXI3 master sets WID equal to AWID on every beat and does not interleave
write data; the AXI3 slave demuxes W beats by WID so it can accept interleaved
write data from other masters.  See issue #87.
"""

import collections
import random
from typing import Any, Dict, List, Optional, Union

import cocotb
from cocotb.triggers import Event, Lock, RisingEdge

from CocoTBFramework.components.axi3.axi3_field_configs import AXI3FieldConfigHelper
from CocoTBFramework.components.gaxi.gaxi_master import GAXIMaster
from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave
from CocoTBFramework.components.shared.memory_model import oor_read_data
from CocoTBFramework.components.shared.id_order import new_waiters, release, take_ticket, wait_turn


class AXI3MasterRead:
    """AXI3 Master Read Interface."""

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI3 Master Read interface."""
        self.super_debug = True
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)
        self.optional_fields = kwargs.get('optional_fields')

        self.ar_channel = GAXIMaster(
            dut=dut,
            title=f"AR_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_ar_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="ar",
            multi_sig=self.multi_sig,
            protocol_type='axi3_ar_master',
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        self.r_channel = GAXISlave(
            dut=dut,
            title=f"R_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_r_field_config(
                self.id_width, self.data_width, self.user_width
            ),
            pkt_prefix="r",
            multi_sig=self.multi_sig,
            protocol_type='axi3_r_slave',
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        self.timeout_cycles = kwargs.get('timeout_cycles', 5000)

        self._response_by_id = collections.defaultdict(collections.deque)
        self._waiters_by_id = new_waiters()  # same-ID calls in issue order (RDS-DV #94)
        self.r_channel.add_callback(self._on_r_response)

    def _on_r_response(self, pkt):
        """Route incoming R beat into its per-ID deque."""
        pkt_id = getattr(pkt, 'id', 0)
        self._response_by_id[pkt_id].append(pkt)

    async def read_transaction(self, address: int, burst_len: int = 1, **transaction_kwargs) -> List[int]:
        """High-level read transaction using generic field names."""
        if not (1 <= burst_len <= 16):
            raise ValueError(f"AXI3 burst length must be 1-16 beats, got {burst_len}")

        txn_id = transaction_kwargs.get('id', 0)
        full_bus_size = (self.data_width // 8).bit_length() - 1

        ar_packet = self.ar_channel.create_packet(
            addr=address,
            len=burst_len - 1,
            id=txn_id,
            size=transaction_kwargs.get('size', full_bus_size),
            burst=transaction_kwargs.get('burst_type', 1),
            lock=transaction_kwargs.get('lock', 0),
            cache=transaction_kwargs.get('cache', 0),
            prot=transaction_kwargs.get('prot', 0),
        )

        if 'user' in transaction_kwargs and hasattr(ar_packet, 'user'):
            ar_packet.user = transaction_kwargs['user']

        _ticket = take_ticket(self._waiters_by_id, txn_id)  # wire order (RDS-DV #94)
        try:
            await self.ar_channel.send(ar_packet)
        except BaseException:
            release(self._waiters_by_id, txn_id, _ticket)
            raise

        # Served in issue order among same-ID calls (RDS-DV #94):
        # a call takes its beats only at the head of its ID's line.
        id_queue = collections.deque(await wait_turn(
            self.clock, self._waiters_by_id, self._response_by_id, txn_id, _ticket,
            burst_len, self.timeout_cycles, lambda c, r: f"AXI3 read timeout after {c} cycles: got {r} of {burst_len} responses at address 0x{address:08X} (id={txn_id})"))

        read_data = []
        for _ in range(burst_len):
            packet = id_queue.popleft()
            data_value = getattr(packet, 'data', 0)
            read_data.append(data_value)

            if hasattr(packet, 'resp') and packet.resp != 0:
                resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
                resp_name = resp_names.get(packet.resp, 'UNKNOWN')
                raise RuntimeError(f"AXI3 read error: {resp_name} (0x{packet.resp:X})")

        return read_data

    async def single_read(self, address: int, **kwargs) -> int:
        """Convenience method for single read."""
        data_list = await self.read_transaction(address, burst_len=1, **kwargs)
        return data_list[0]

    def create_ar_packet(self, **kwargs):
        """Create AR packet with current configuration."""
        return self.ar_channel.create_packet(**kwargs)


class AXI3MasterWrite:
    """AXI3 Master Write Interface.

    The master sets WID equal to AWID on every beat and streams each burst
    contiguously.  This is the simplest legal AXI3 behaviour and is documented
    here explicitly; the master does not exercise write-data interleaving.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI3 Master Write interface."""
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)
        self.optional_fields = kwargs.get('optional_fields')

        self.aw_channel = GAXIMaster(
            dut=dut,
            title=f"AW_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_aw_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="aw",
            multi_sig=self.multi_sig,
            protocol_type='axi3_aw_master',
            log=log,
            optional_fields=self.optional_fields,
        )

        self.w_channel = GAXIMaster(
            dut=dut,
            title=f"W_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_w_field_config(
                self.id_width, self.data_width, self.user_width
            ),
            pkt_prefix="w",
            multi_sig=self.multi_sig,
            protocol_type='axi3_w_master',
            log=log,
            optional_fields=self.optional_fields,
        )

        self.b_channel = GAXISlave(
            dut=dut,
            title=f"B_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_b_field_config(
                self.id_width, self.user_width
            ),
            pkt_prefix="b",
            multi_sig=self.multi_sig,
            protocol_type='axi3_b_slave',
            log=log,
            optional_fields=self.optional_fields,
        )

        self.timeout_cycles = kwargs.get('timeout_cycles', 5000)

        self._response_by_id = collections.defaultdict(collections.deque)
        self._waiters_by_id = new_waiters()  # same-ID calls in issue order (RDS-DV #94)
        self.b_channel.add_callback(self._on_b_response)

        self._aw_lock = Lock(name=f"AW_Lock{self.ifc_name}")
        self._w_prev_done = None

    def _on_b_response(self, pkt):
        """Route incoming B response into its per-ID deque."""
        pkt_id = getattr(pkt, 'id', 0)
        self._response_by_id[pkt_id].append(pkt)

    async def write_transaction(self, address: int, data: Union[int, List[int]],
                            burst_len: Optional[int] = None, **transaction_kwargs) -> Dict[str, Any]:
        """High-level write transaction using generic field names."""
        aw_packet = None

        _ticket = None
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

            if not (1 <= burst_len <= 16):
                raise ValueError(f"AXI3 burst length must be 1-16 beats, got {burst_len}")

            txn_id = transaction_kwargs.get('id', 0)
            full_bus_size = (self.data_width // 8).bit_length() - 1

            aw_packet = self.aw_channel.create_packet(
                addr=address,
                len=burst_len - 1,
                id=txn_id,
                size=transaction_kwargs.get('size', full_bus_size),
                burst=transaction_kwargs.get('burst_type', 1),
                lock=transaction_kwargs.get('lock', 0),
                cache=transaction_kwargs.get('cache', 0),
                prot=transaction_kwargs.get('prot', 0),
            )

            if 'user' in transaction_kwargs and hasattr(aw_packet, 'user'):
                aw_packet.user = transaction_kwargs['user']

            my_w_done = Event(name=f"W_Done{self.ifc_name}")
            async with self._aw_lock:
                prev_w_done = self._w_prev_done
                self._w_prev_done = my_w_done
                _ticket = take_ticket(self._waiters_by_id, txn_id)  # wire order (RDS-DV #94)
                await self.aw_channel.send(aw_packet)

            try:
                if prev_w_done is not None:
                    await prev_w_done.wait()

                strb_width = self.data_width // 8
                beat_bytes = 1 << aw_packet.size

                w_packets = []
                for i, data_value in enumerate(data_list):
                    if 'strb' in transaction_kwargs:
                        beat_strb = transaction_kwargs['strb']
                    elif beat_bytes >= strb_width:
                        beat_strb = (1 << strb_width) - 1
                    else:
                        lane = (address + i * beat_bytes) % strb_width
                        beat_strb = ((1 << beat_bytes) - 1) << lane
                        data_value = (data_value & ((1 << (beat_bytes * 8)) - 1)) << (lane * 8)
                    w_packets.append(self.w_channel.create_packet(
                        id=txn_id,
                        data=data_value,
                        last=1 if i == len(data_list) - 1 else 0,
                        strb=beat_strb,
                        **{k: v for k, v in transaction_kwargs.items() if k.startswith('w')}
                    ))
                await self.w_channel.send_burst(w_packets)
            finally:
                my_w_done.set()

            # Served in issue order among same-ID calls (RDS-DV #94):
            # a call takes its beats only at the head of its ID's line.
            id_queue = collections.deque(await wait_turn(
                self.clock, self._waiters_by_id, self._response_by_id, txn_id, _ticket,
                1, self.timeout_cycles, lambda c, r: f"AXI3 write timeout after {c} cycles: waiting for B response at address 0x{address:08X} (id={txn_id})"))

            b_response = id_queue.popleft()

            resp_code = b_response.resp if hasattr(b_response, 'resp') else 0
            result = {
                'success': True,
                'response': resp_code,
                'id': b_response.id if hasattr(b_response, 'id') else 0
            }
            if resp_code != 0:
                resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
                resp_name = resp_names.get(resp_code, 'UNKNOWN')
                result['success'] = False
                result['error'] = f"AXI3 write error: {resp_name} (0x{resp_code:X})"
                if self.log:
                    self.log.error(f"AXI3 write transaction failed: addr=0x{address:08X}, "
                                   f"error: {result['error']}")
            return result

        except Exception as e:
            if _ticket is not None:  # leave the ID line (RDS-DV #94)
                release(self._waiters_by_id, txn_id, _ticket)
            if self.log:
                addr_str = f"addr=0x{address:08X}" if address is not None else "addr=None"
                data_str = f"data=0x{data:08X}" if isinstance(data, int) else f"data={type(data).__name__}"
                packet_str = f"aw_packet={'created' if aw_packet is not None else 'not_created'}"
                self.log.error(f"AXI3 write transaction failed: {addr_str}, {data_str}, {packet_str}, error: {str(e)}")

            return {
                'success': False,
                'error': str(e),
                'response': None,
                'id': None
            }

    async def single_write(self, address: int, data: int, **kwargs) -> Dict[str, Any]:
        """Convenience method for single write."""
        return await self.write_transaction(address, data, burst_len=1, **kwargs)


class AXI3SlaveRead:
    """AXI3 Slave Read Interface."""

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI3 Slave Read interface."""
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)

        self.memory_model = kwargs.get('memory_model')
        self.base_addr = kwargs.get('base_addr', 0)
        self.response_delay_cycles = kwargs.get('response_delay', 1)
        self.resp_override = kwargs.get('resp_override')

        self.enable_ooo = kwargs.get('enable_ooo', False)
        self.ooo_config = kwargs.get('ooo_config', {
            'mode': 'random',
            'reorder_probability': 0.3,
            'min_delay_cycles': 1,
            'max_delay_cycles': 50,
            'pattern': None,
        })

        self.ooo_transaction_sequence = 0
        self.ooo_transaction_metadata = {}
        self.ooo_last_completed_seq = {}

        self.in_order_active = {}
        self.in_order_queue = {}

        self.optional_fields = kwargs.get('optional_fields')

        self.ar_channel = GAXISlave(
            dut=dut,
            title=f"AR_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_ar_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="ar",
            multi_sig=self.multi_sig,
            protocol_type='axi3_ar_slave',
            log=log,
            optional_fields=self.optional_fields,
        )

        self.r_channel = GAXIMaster(
            dut=dut,
            title=f"R_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_r_field_config(
                self.id_width, self.data_width, self.user_width
            ),
            pkt_prefix="r",
            multi_sig=self.multi_sig,
            protocol_type='axi3_r_master',
            log=log,
            super_debug=True,
            optional_fields=self.optional_fields,
        )

        self.ar_channel.add_callback(self._ar_callback)

        if self.log:
            mode_str = "OOO mode ENABLED" if self.enable_ooo else "In-order mode"
            if self.enable_ooo:
                mode_str += f" (reorder_prob={self.ooo_config.get('reorder_probability', 0.3)}, " \
                        f"delay=[{self.ooo_config.get('min_delay_cycles', 1)}, " \
                        f"{self.ooo_config.get('max_delay_cycles', 50)}])"
            self.log.info(f"AXI3SlaveRead initialized: AR callback linked to R master, {mode_str}")

    def _ar_callback(self, ar_packet):
        """Callback triggered when AR slave receives a packet."""
        transaction_id = getattr(ar_packet, 'id', 0)
        addr = getattr(ar_packet, 'addr', 0)

        if self.enable_ooo:
            txn_sequence = self.ooo_transaction_sequence
            self.ooo_transaction_sequence += 1
            self.ooo_transaction_metadata[txn_sequence] = {
                'id': transaction_id,
                'addr': addr
            }
            ar_packet._ooo_sequence = txn_sequence
            seq_str = f", seq={txn_sequence}"
        else:
            seq_str = ""

        if self.log:
            self.log.debug(f"AXI3SlaveRead: AR callback triggered - "
                        f"addr=0x{addr:08X}, id={transaction_id}{seq_str}")

        if self.enable_ooo:
            delay_cycles = self._calculate_ooo_delay_read(ar_packet)
            if self.log:
                self.log.debug(f"AXI3SlaveRead: Scheduling OOO completion for "
                            f"txn {transaction_id} after {delay_cycles} cycles")
            cocotb.start_soon(self._generate_read_response_delayed(ar_packet, delay_cycles))
        else:
            cocotb.start_soon(self._generate_read_response_serialized(ar_packet))

    def _calculate_ooo_delay_read(self, ar_packet):
        """Calculate delay cycles for OOO read response."""
        txn_sequence = getattr(ar_packet, '_ooo_sequence', None)
        if txn_sequence is None:
            return 1

        transaction_id = getattr(ar_packet, 'id', 0)
        txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
        txn_id = txn_meta.get('id', transaction_id)

        last_completed = self.ooo_last_completed_seq.get(txn_id, -1)

        blocking_sequences = []
        for seq, meta in self.ooo_transaction_metadata.items():
            if meta['id'] == txn_id and seq < txn_sequence and seq > last_completed:
                blocking_sequences.append(seq)

        if blocking_sequences:
            return 100

        mode = self.ooo_config.get('mode', 'random')

        if mode == 'deterministic':
            pattern = self.ooo_config.get('pattern', [])
            if pattern and txn_sequence < len(pattern):
                try:
                    target_position = pattern.index(txn_sequence)
                    current_position = len([s for s in self.ooo_last_completed_seq.values() if s >= 0])

                    if target_position > current_position:
                        return (target_position - current_position) * 20
                    return 1
                except ValueError:
                    return self.ooo_config.get('min_delay_cycles', 1)
            else:
                return self.ooo_config.get('min_delay_cycles', 1)

        elif mode == 'random':
            min_delay = self.ooo_config.get('min_delay_cycles', 1)
            max_delay = self.ooo_config.get('max_delay_cycles', 50)
            base_delay = random.randint(min_delay, max_delay)

            reorder_prob = self.ooo_config.get('reorder_probability', 0.3)
            if random.random() < reorder_prob:
                extra_delay = random.randint(20, 50)
                return base_delay + extra_delay
            return base_delay

        return 1

    async def _generate_read_response_serialized(self, ar_packet):
        """Generate read response with serialization for in-order mode."""
        transaction_id = getattr(ar_packet, 'id', 0)

        if transaction_id not in self.in_order_queue:
            self.in_order_queue[transaction_id] = []
            self.in_order_active[transaction_id] = False

        self.in_order_queue[transaction_id].append(ar_packet)

        if self.in_order_active[transaction_id]:
            return

        self.in_order_active[transaction_id] = True

        while self.in_order_queue[transaction_id]:
            packet = self.in_order_queue[transaction_id].pop(0)
            await self._generate_read_response(packet)

        self.in_order_active[transaction_id] = False

    async def _generate_read_response_delayed(self, ar_packet, delay_cycles):
        """Generate read response after specified delay (OOO mode)."""
        for _ in range(delay_cycles):
            await RisingEdge(self.clock)
        await self._generate_read_response(ar_packet)

    async def _generate_read_response(self, ar_packet):
        """Generate R response for an AR request."""
        try:
            address = getattr(ar_packet, 'addr', 0)
            burst_len = getattr(ar_packet, 'len', 0) + 1
            packet_id = getattr(ar_packet, 'id', 0)
            size_encoding = getattr(ar_packet, 'size', 2)
            bytes_per_beat = 1 << size_encoding

            if self.log:
                self.log.debug(f"AXI3SlaveRead: Generating {burst_len} beat response for "
                            f"addr=0x{address:08X}, id={packet_id}")

            for _ in range(self.response_delay_cycles):
                await RisingEdge(self.clock)

            r_packets = []
            for i in range(burst_len):
                current_addr = address + (i * bytes_per_beat)

                beat_resp = 0
                if self.memory_model:
                    memory_offset = current_addr - self.base_addr
                    if not self.memory_model.in_range(memory_offset, bytes_per_beat):
                        self.memory_model.oor_warning(self.log, 'AXI3SlaveRead',
                                                      current_addr, bytes_per_beat, packet_id)
                        data = oor_read_data(bytes_per_beat)
                        beat_resp = 2
                    else:
                        try:
                            data_bytes = self.memory_model.read(memory_offset, bytes_per_beat)
                            data = self.memory_model.bytearray_to_integer(data_bytes)
                            if self.log:
                                self.log.debug(f"AXI3SlaveRead: Read from memory - "
                                            f"addr=0x{current_addr:08X}, data=0x{data:08X}")
                        except Exception as e:
                            if self.log:
                                self.log.warning(f"AXI3SlaveRead: memory read failed at "
                                                 f"0x{current_addr:08X}: {e} -- answering SLVERR")
                            data = oor_read_data(bytes_per_beat)
                            beat_resp = 2
                else:
                    data = current_addr

                bus_bytes = self.data_width // 8
                if self.memory_model and bytes_per_beat < bus_bytes:
                    lane = current_addr % bus_bytes
                    data = (data & ((1 << (bytes_per_beat * 8)) - 1)) << (lane * 8)

                is_last = (i == burst_len - 1)
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

            for r_packet in r_packets:
                self.r_channel.transmit_queue.append(r_packet)

            if not self.r_channel.transmit_coroutine:
                self.r_channel.transmit_coroutine = cocotb.start_soon(self.r_channel._transmit_pipeline())

            if self.enable_ooo:
                txn_sequence = getattr(ar_packet, '_ooo_sequence', None)
                if txn_sequence is not None:
                    txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
                    txn_id = txn_meta.get('id', packet_id)
                    self.ooo_last_completed_seq[txn_id] = txn_sequence

        except Exception as e:
            if self.log:
                self.log.error(f"AXI3SlaveRead: Error generating response: {e}")


class AXI3SlaveWrite:
    """AXI3 Slave Write Interface.

    Properly handles AXI3 write data interleaving by WID.  W beats are
    buffered per WID and matched to AW transactions of the same ID.
    """

    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs):
        """Initialize AXI3 Slave Write interface."""
        self.super_debug = kwargs.get('super_debug', False)
        self.clock = clock
        self.log = log
        self.ifc_name = f"_{ifc_name}" if ifc_name else ""

        self.data_width = kwargs.get('data_width', 32)
        self.id_width = kwargs.get('id_width', 8)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 1)
        self.multi_sig = kwargs.get('multi_sig', True)

        self.memory_model = kwargs.get('memory_model')
        self.base_addr = kwargs.get('base_addr', 0)
        self.response_delay_cycles = kwargs.get('response_delay', 1)

        self.enable_ooo = kwargs.get('enable_ooo', False)
        self.ooo_config = kwargs.get('ooo_config', {
            'mode': 'random',
            'reorder_probability': 0.3,
            'min_delay_cycles': 1,
            'max_delay_cycles': 50,
            'pattern': None,
        })

        self.ooo_transaction_sequence = 0
        self.ooo_transaction_metadata = {}
        self.ooo_last_completed_seq = {}

        self.optional_fields = kwargs.get('optional_fields')

        self.aw_channel = GAXISlave(
            dut=dut,
            title=f"AW_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_aw_field_config(
                self.id_width, self.addr_width, self.user_width
            ),
            pkt_prefix="aw",
            multi_sig=self.multi_sig,
            protocol_type='axi3_aw_slave',
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        self.w_channel = GAXISlave(
            dut=dut,
            title=f"W_Slave{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_w_field_config(
                self.id_width, self.data_width, self.user_width
            ),
            pkt_prefix="w",
            multi_sig=self.multi_sig,
            protocol_type='axi3_w_slave',
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        self.b_channel = GAXIMaster(
            dut=dut,
            title=f"B_Master{self.ifc_name}",
            prefix=prefix,
            clock=clock,
            field_config=AXI3FieldConfigHelper.create_b_field_config(
                self.id_width, self.user_width
            ),
            pkt_prefix="b",
            multi_sig=self.multi_sig,
            protocol_type='axi3_b_master',
            super_debug=self.super_debug,
            log=log,
            optional_fields=self.optional_fields,
        )

        self.aw_channel.add_callback(self._aw_callback)
        self.w_channel.add_callback(self._w_callback)

        # Per-ID transaction tracking, with per-WID buffering for interleaved W data.
        self.pending_transactions = {}      # id -> [txn_list]
        self.orphaned_w_packets = {}        # w_id -> [partial beats]
        self.w_transaction_queue = {}       # w_id -> [[complete burst], ...]
        self.completion_locks = {}          # id -> Lock

        if self.log:
            mode_str = "OOO mode ENABLED" if self.enable_ooo else "In-order mode"
            if self.enable_ooo:
                mode_str += f" (reorder_prob={self.ooo_config.get('reorder_probability', 0.3)}, " \
                        f"delay=[{self.ooo_config.get('min_delay_cycles', 1)}, " \
                        f"{self.ooo_config.get('max_delay_cycles', 50)}])"
            self.log.info(f"AXI3SlaveWrite initialized: AW/W callbacks linked to B master with WID demux, {mode_str}")

    def _aw_callback(self, aw_packet):
        """Handle AW packet reception."""
        transaction_id = getattr(aw_packet, 'id', 0)
        burst_len = getattr(aw_packet, 'len', 0) + 1
        addr = getattr(aw_packet, 'addr', 0)

        txn_sequence = self.ooo_transaction_sequence
        self.ooo_transaction_sequence += 1
        if self.enable_ooo:
            self.ooo_transaction_metadata[txn_sequence] = {
                'id': transaction_id,
                'addr': addr
            }

        if transaction_id not in self.pending_transactions:
            self.pending_transactions[transaction_id] = []

        self.pending_transactions[transaction_id].append({
            'aw_packet': aw_packet,
            'w_packets': [],
            'expected_beats': burst_len,
            'complete': False,
            'sequence': txn_sequence
        })

        if self.log:
            seq_str = f", seq={txn_sequence}" if self.enable_ooo else ""
            self.log.debug(f"AXI3SlaveWrite: AW received - id={transaction_id}, "
                        f"addr=0x{addr:08X}, expected_beats={burst_len}{seq_str}")

        self._match_orphaned_w_packets(transaction_id)

    def _w_callback(self, w_packet):
        """Handle W packet reception, demuxing by WID."""
        is_last = getattr(w_packet, 'last', 0)
        data_val = getattr(w_packet, 'data', 0)
        w_id = getattr(w_packet, 'id', 0)

        if self.log:
            self.log.debug(f"AXI3SlaveWrite: W received - data=0x{data_val:08X}, last={is_last}, id={w_id}")

        # Find an incomplete pending transaction for this WID.
        transaction = None
        if w_id in self.pending_transactions:
            for txn in self.pending_transactions[w_id]:
                if not txn['complete']:
                    transaction = txn
                    break

        if transaction is None:
            # No matching AW yet (or only complete-pending-cleanup txns) -- buffer by WID.
            if self.log:
                self.log.debug(f"AXI3SlaveWrite: W id={w_id} arrived before matching AW - buffering")
            self.orphaned_w_packets.setdefault(w_id, []).append(w_packet)
            if is_last:
                self.w_transaction_queue.setdefault(w_id, []).append(self.orphaned_w_packets[w_id].copy())
                self.orphaned_w_packets[w_id].clear()
            return

        transaction['w_packets'].append(w_packet)

        if is_last or len(transaction['w_packets']) >= transaction['expected_beats']:
            transaction['complete'] = True
            if self.log:
                self.log.debug(f"AXI3SlaveWrite: Transaction id={w_id} complete")

            if self.enable_ooo:
                delay_cycles = self._calculate_ooo_delay(w_id)
                cocotb.start_soon(self._complete_write_transaction_delayed(w_id, delay_cycles))
            else:
                cocotb.start_soon(self._complete_write_transaction(w_id))

    def _match_orphaned_w_packets(self, aw_id):
        """Match orphaned W packets/bursts to a newly arrived AW transaction."""
        if aw_id not in self.pending_transactions:
            return

        transaction = None
        for txn in self.pending_transactions[aw_id]:
            if not txn['complete']:
                transaction = txn
                break

        if transaction is None:
            return

        # First try a complete queued burst for this WID.
        if aw_id in self.w_transaction_queue and self.w_transaction_queue[aw_id]:
            w_burst = self.w_transaction_queue[aw_id].pop(0)
            transaction['w_packets'] = w_burst
            transaction['complete'] = True
            if self.log:
                self.log.debug(f"AXI3SlaveWrite: Matched orphaned W burst ({len(w_burst)} beats) to AW id={aw_id}")
            if self.enable_ooo:
                delay_cycles = self._calculate_ooo_delay(aw_id)
                cocotb.start_soon(self._complete_write_transaction_delayed(aw_id, delay_cycles))
            else:
                cocotb.start_soon(self._complete_write_transaction(aw_id))
            return

        # Otherwise, absorb any partial buffered beats for this WID.
        if aw_id in self.orphaned_w_packets and self.orphaned_w_packets[aw_id]:
            transaction['w_packets'] = self.orphaned_w_packets[aw_id].copy()
            self.orphaned_w_packets[aw_id].clear()
            if self.log:
                self.log.debug(f"AXI3SlaveWrite: Matched {len(transaction['w_packets'])} partial orphaned W packets to AW id={aw_id}, "
                             f"expecting {transaction['expected_beats']} total beats")

    def _calculate_ooo_delay(self, transaction_id):
        """Calculate delay cycles for OOO response."""
        if transaction_id not in self.pending_transactions:
            return 1

        txn_list = self.pending_transactions[transaction_id]
        if not txn_list:
            return 1

        txn = txn_list[0]
        txn_sequence = txn.get('sequence')
        if txn_sequence is None:
            return 1

        txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
        txn_id = txn_meta.get('id', transaction_id)

        last_completed = self.ooo_last_completed_seq.get(txn_id, -1)

        blocking_sequences = []
        for seq, meta in self.ooo_transaction_metadata.items():
            if meta['id'] == txn_id and seq < txn_sequence and seq > last_completed:
                blocking_sequences.append(seq)

        if blocking_sequences:
            return 100

        mode = self.ooo_config.get('mode', 'random')

        if mode == 'deterministic':
            pattern = self.ooo_config.get('pattern', [])
            if pattern and txn_sequence < len(pattern):
                try:
                    target_position = pattern.index(txn_sequence)
                    current_position = len([s for s in self.ooo_last_completed_seq.values() if s >= 0])

                    if target_position > current_position:
                        return (target_position - current_position) * 20
                    return 1
                except ValueError:
                    return self.ooo_config.get('min_delay_cycles', 1)
            else:
                return self.ooo_config.get('min_delay_cycles', 1)

        elif mode == 'random':
            min_delay = self.ooo_config.get('min_delay_cycles', 1)
            max_delay = self.ooo_config.get('max_delay_cycles', 50)
            base_delay = random.randint(min_delay, max_delay)

            reorder_prob = self.ooo_config.get('reorder_probability', 0.3)
            if random.random() < reorder_prob:
                extra_delay = random.randint(20, 50)
                return base_delay + extra_delay
            return base_delay

        return 1

    async def _complete_write_transaction_delayed(self, transaction_id, delay_cycles):
        """Complete write transaction after specified delay (OOO mode)."""
        for _ in range(delay_cycles):
            await RisingEdge(self.clock)
        await self._complete_write_transaction(transaction_id)

    async def _complete_write_transaction(self, transaction_id):
        """Complete write transaction and send B response."""
        if transaction_id not in self.completion_locks:
            self.completion_locks[transaction_id] = Lock(
                name=f"AXI3SlaveWrite_completion_id{transaction_id}")

        async with self.completion_locks[transaction_id]:
            if transaction_id not in self.pending_transactions:
                return

            transaction_list = self.pending_transactions[transaction_id]
            if not transaction_list:
                return

            transaction = None
            for txn in transaction_list:
                if txn['complete'] and not txn.get('completing', False):
                    transaction = txn
                    break

            if transaction is None:
                return

            transaction['completing'] = True

        if self.enable_ooo:
            txn_sequence = transaction.get('sequence')
            if txn_sequence is not None:
                txn_meta = self.ooo_transaction_metadata.get(txn_sequence, {})
                txn_id = txn_meta.get('id', transaction_id)
                self.ooo_last_completed_seq[txn_id] = txn_sequence

        aw_packet = transaction['aw_packet']
        w_packets = transaction['w_packets']

        try:
            base_addr = getattr(aw_packet, 'addr', 0)
            size_encoding = getattr(aw_packet, 'size', 2)
            bytes_per_beat = 1 << size_encoding

            resp = 0
            if self.memory_model:
                bus_bytes = self.data_width // 8
                first_off = (base_addr - (base_addr % bus_bytes)) - self.base_addr
                last_addr = base_addr + (len(w_packets) - 1) * bytes_per_beat
                span = (last_addr - (last_addr % bus_bytes)) + bus_bytes - (base_addr - (base_addr % bus_bytes))
                if not self.memory_model.in_range(first_off, span):
                    self.memory_model.oor_warning(self.log, 'AXI3SlaveWrite',
                                                  base_addr, span, transaction_id)
                    resp = 2
                    w_packets_to_write = []
                else:
                    w_packets_to_write = w_packets

                for i, w_packet in enumerate(w_packets_to_write):
                    addr = base_addr + (i * bytes_per_beat)
                    bus_aligned_addr = addr - (addr % bus_bytes)
                    memory_offset = bus_aligned_addr - self.base_addr

                    data = getattr(w_packet, 'data', 0)
                    strb = getattr(w_packet, 'strb', (1 << bus_bytes) - 1)

                    try:
                        data_bytes = self.memory_model.integer_to_bytearray(data, bus_bytes)
                        self.memory_model.write(memory_offset, data_bytes, strb)
                    except Exception as mem_error:
                        if self.log:
                            self.log.warning(f"AXI3SlaveWrite: memory write failed for txn "
                                             f"{transaction_id}: {mem_error} -- answering SLVERR")
                        resp = 2

            if self.response_delay_cycles > 0:
                for _ in range(self.response_delay_cycles):
                    await RisingEdge(self.clock)

            if transaction_id not in self.pending_transactions:
                return

            b_packet = self.b_channel.create_packet(
                id=transaction_id,
                resp=resp
            )

            await self.b_channel.send(b_packet)

            if self.log:
                self.log.debug(f"AXI3SlaveWrite: B response sent - id={transaction_id}, "
                            f"addr=0x{base_addr:08X}, beats={len(w_packets)}")

        except Exception as e:
            if self.log:
                self.log.error(f"AXI3SlaveWrite: Error completing transaction {transaction_id}: {e}")
        finally:
            if transaction_id in self.pending_transactions:
                transaction_list = self.pending_transactions[transaction_id]
                if transaction in transaction_list:
                    transaction_list.remove(transaction)
                    if self.log:
                        self.log.debug(f"AXI3SlaveWrite: Transaction {transaction_id} removed from list "
                                    f"({len(transaction_list)} remaining)")

                if not transaction_list:
                    del self.pending_transactions[transaction_id]

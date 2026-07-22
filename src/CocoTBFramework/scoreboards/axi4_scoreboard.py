# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI4Scoreboard
# Purpose: AXI4 Scoreboard for Verification
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXI4 Scoreboard for Verification

This module provides scoreboard functionality for verifying AXI4 transactions.
"""

from cocotb.utils import get_sim_time

from CocoTBFramework.scoreboards.base_scoreboard import BaseScoreboard


class AXI4Scoreboard(BaseScoreboard):
    """
    Scoreboard for AXI4 protocol transactions.

    This class provides:
    - Tracking and matching of master and slave-side transactions
    - Protocol compliance checking
    - Transaction statistics
    """

    def __init__(self, name, id_width=8, addr_width=32, data_width=32, user_width=1, log=None):
        """
        Initialize AXI4 Scoreboard.

        Args:
            name: Scoreboard name
            id_width: Width of ID fields (default: 8)
            addr_width: Width of address fields (default: 32)
            data_width: Width of data fields (default: 32)
            user_width: Width of user fields (default: 1)
            log: Logger instance
        """
        super().__init__(name, log)

        # Additional counters for AXI4-specific statistics
        self.write_count = 0
        self.read_count = 0
        self.protocol_error_count = 0

        # Transaction queues
        self.master_writes = {}  # Maps IDs to master-side write transactions
        self.slave_writes = {}   # Maps IDs to slave-side write transactions
        self.master_reads = {}   # Maps IDs to master-side read transactions
        self.slave_reads = {}    # Maps IDs to slave-side read transactions

        # Store monitors for easy access
        self.master_monitor = None
        self.slave_monitor = None

        # Field dimensions
        self.id_width = id_width
        self.addr_width = addr_width
        self.data_width = data_width
        self.user_width = user_width

    @staticmethod
    def _get_field(obj, *names):
        """
        Get the first available field from an object or dict, trying each name.

        Framework packets use generic field names ('addr', 'data', 'resp', ...)
        while AXI-style transaction objects use prefixed names ('awaddr',
        'wdata', 'rresp', ...). This helper makes match logic work with both.

        Returns None if no name resolves.
        """
        for name in names:
            if isinstance(obj, dict):
                if name in obj:
                    return obj[name]
            elif hasattr(obj, name):
                return getattr(obj, name)
        return None

    def _register_monitor(self, monitor, write_handler, read_handler, side):
        """
        Register scoreboard callbacks on a monitor.

        Supports two callback mechanisms:
        - Custom monitors exposing set_write_callback()/set_read_callback(),
          which are called with (id_value, transaction).
        - Framework monitors (GAXIMonitor / cocotb_bus BusMonitor) exposing
          add_callback(), which is called with (transaction). Transactions are
          classified as read or write and their ID extracted automatically.
        """
        if hasattr(monitor, 'set_write_callback') and hasattr(monitor, 'set_read_callback'):
            monitor.set_write_callback(write_handler)
            monitor.set_read_callback(read_handler)
        elif hasattr(monitor, 'add_callback'):
            monitor.add_callback(
                lambda transaction: self._route_monitor_transaction(
                    transaction, write_handler, read_handler, side
                )
            )
        else:
            raise ValueError(
                f"{side} monitor {monitor!r} provides neither "
                "set_write_callback()/set_read_callback() nor add_callback()"
            )

    def _route_monitor_transaction(self, transaction, write_handler, read_handler, side):
        """Classify a monitor transaction as read/write and dispatch it."""
        is_write = any(
            self._get_field(transaction, key) is not None
            for key in ('aw_transaction', 'w_transactions', 'b_transaction')
        )
        is_read = any(
            self._get_field(transaction, key) is not None
            for key in ('ar_transaction', 'r_transactions')
        )

        if is_write and not is_read:
            write_handler(self._extract_transaction_id(transaction, is_write=True), transaction)
        elif is_read and not is_write:
            read_handler(self._extract_transaction_id(transaction, is_write=False), transaction)
        else:
            if self.log:
                self.log.warning(
                    f"{self.name} - Could not classify {side} monitor transaction "
                    f"as read or write: {transaction!r}"
                )

    def _extract_transaction_id(self, transaction, is_write):
        """Extract the AXI4 transaction ID from a composite transaction."""
        id_value = self._get_field(transaction, 'id', 'txn_id')
        if id_value is not None:
            return id_value

        # Fall back to the per-channel packets that carry the ID
        if is_write:
            candidates = [
                (self._get_field(transaction, 'aw_transaction'), ('awid', 'id')),
                (self._get_field(transaction, 'b_transaction'), ('bid', 'id')),
            ]
        else:
            r_transactions = self._get_field(transaction, 'r_transactions') or []
            candidates = [
                (self._get_field(transaction, 'ar_transaction'), ('arid', 'id')),
                (r_transactions[0] if r_transactions else None, ('rid', 'id')),
            ]

        for channel_tx, id_names in candidates:
            if channel_tx is not None:
                id_value = self._get_field(channel_tx, *id_names)
                if id_value is not None:
                    return id_value
        return 0

    def add_master_monitor(self, monitor):
        """Connect a master-side AXI4 monitor to the scoreboard"""
        self.master_monitor = monitor
        self._register_monitor(
            monitor, self._handle_master_write, self._handle_master_read, 'master'
        )

    def add_slave_monitor(self, monitor):
        """Connect a slave-side AXI4 monitor to the scoreboard"""
        self.slave_monitor = monitor
        self._register_monitor(
            monitor, self._handle_slave_write, self._handle_slave_read, 'slave'
        )

    def _handle_master_write(self, id_value, transaction):
        """Process a completed write transaction from the master side"""
        self.master_writes[id_value] = transaction

        # Check for matching slave-side transaction
        if id_value in self.slave_writes and not self.slave_writes[id_value].get('matched', False):
            # Both sides have transactions, check if they match
            self._check_write_match(id_value, self.master_writes[id_value], self.slave_writes[id_value])

    def _handle_slave_write(self, id_value, transaction):
        """Process a completed write transaction from the slave side"""
        self.slave_writes[id_value] = transaction

        # Check for matching master-side transaction
        if id_value in self.master_writes and not self.master_writes[id_value].get('matched', False):
            # Both sides have transactions, check if they match
            self._check_write_match(id_value, self.master_writes[id_value], self.slave_writes[id_value])

    def _handle_master_read(self, id_value, transaction):
        """Process a completed read transaction from the master side"""
        self.master_reads[id_value] = transaction

        # Check for matching slave-side transaction
        if id_value in self.slave_reads and not self.slave_reads[id_value].get('matched', False):
            # Both sides have transactions, check if they match
            self._check_read_match(id_value, self.master_reads[id_value], self.slave_reads[id_value])

    def _handle_slave_read(self, id_value, transaction):
        """Process a completed read transaction from the slave side"""
        self.slave_reads[id_value] = transaction

        # Check for matching master-side transaction
        if id_value in self.master_reads and not self.master_reads[id_value].get('matched', False):
            # Both sides have transactions, check if they match
            self._check_read_match(id_value, self.master_reads[id_value], self.slave_reads[id_value])

    def _compare_channel_field(self, label, master_obj, slave_obj, names, mismatches, hex_format=False):
        """
        Compare one field between master and slave channel transactions.

        Tries each name in `names` on both objects (supporting AXI-prefixed
        names such as 'awaddr' and generic framework names such as 'addr').
        Appends a description to `mismatches` when the values differ or when
        the field is present on only one side.
        """
        master_val = self._get_field(master_obj, *names)
        slave_val = self._get_field(slave_obj, *names)

        if master_val is None and slave_val is None:
            return  # Field not carried by either side; nothing to compare

        if master_val is None or slave_val is None:
            mismatches.append(f"{label}: present on one side only "
                              f"(master={master_val}, slave={slave_val})")
            return

        if master_val != slave_val:
            if hex_format:
                mismatches.append(f"{label}: master=0x{master_val:X}, slave=0x{slave_val:X}")
            else:
                mismatches.append(f"{label}: master={master_val}, slave={slave_val}")

    def _check_write_match(self, id_value, master_tx, slave_tx):
        """Check if master and slave-side write transactions match"""
        mismatches = []

        # Check AW fields
        master_aw = self._get_field(master_tx, 'aw_transaction')
        slave_aw = self._get_field(slave_tx, 'aw_transaction')
        if master_aw is not None and slave_aw is not None:
            self._compare_channel_field('AWADDR', master_aw, slave_aw,
                                        ('awaddr', 'addr'), mismatches, hex_format=True)
            self._compare_channel_field('AWLEN', master_aw, slave_aw,
                                        ('awlen', 'len'), mismatches)
            self._compare_channel_field('AWSIZE', master_aw, slave_aw,
                                        ('awsize', 'size'), mismatches)
            self._compare_channel_field('AWBURST', master_aw, slave_aw,
                                        ('awburst', 'burst'), mismatches)
        else:
            mismatches.append("Missing AW transaction on one side")

        # Check W data
        master_data = [self._get_field(w, 'wdata', 'data')
                       for w in self._get_field(master_tx, 'w_transactions') or []]
        master_data = [d for d in master_data if d is not None]
        slave_data = [self._get_field(w, 'wdata', 'data')
                      for w in self._get_field(slave_tx, 'w_transactions') or []]
        slave_data = [d for d in slave_data if d is not None]

        if len(master_data) != len(slave_data):
            mismatches.append(f"Data beat count: master={len(master_data)}, slave={len(slave_data)}")
        else:
            for i, (master_beat, slave_beat) in enumerate(zip(master_data, slave_data)):
                if master_beat != slave_beat:
                    mismatches.append(f"Data beat {i}: master=0x{master_beat:X}, slave=0x{slave_beat:X}")

        # Check B response
        master_b = self._get_field(master_tx, 'b_transaction')
        slave_b = self._get_field(slave_tx, 'b_transaction')
        if master_b is not None and slave_b is not None:
            self._compare_channel_field('BRESP', master_b, slave_b,
                                        ('bresp', 'resp'), mismatches)
        else:
            mismatches.append("Missing B transaction on one side")

        # Record result
        if mismatches:
            self.error_count += 1
            if self.log:
                self.log.error(f"Write transaction ID={id_value} has mismatches:")
                for mismatch in mismatches:
                    self.log.error(f"  {mismatch}")
        else:
            # Mark as matched
            master_tx['matched'] = True
            slave_tx['matched'] = True
            self.write_count += 1
            if self.log:
                self.log.debug(f"Write transaction ID={id_value} matched between master and slave")

    def _check_read_match(self, id_value, master_tx, slave_tx):
        """Check if master and slave-side read transactions match"""
        mismatches = []

        # Check AR fields
        master_ar = self._get_field(master_tx, 'ar_transaction')
        slave_ar = self._get_field(slave_tx, 'ar_transaction')
        if master_ar is not None and slave_ar is not None:
            self._compare_channel_field('ARADDR', master_ar, slave_ar,
                                        ('araddr', 'addr'), mismatches, hex_format=True)
            self._compare_channel_field('ARLEN', master_ar, slave_ar,
                                        ('arlen', 'len'), mismatches)
            self._compare_channel_field('ARSIZE', master_ar, slave_ar,
                                        ('arsize', 'size'), mismatches)
            self._compare_channel_field('ARBURST', master_ar, slave_ar,
                                        ('arburst', 'burst'), mismatches)
        else:
            mismatches.append("Missing AR transaction on one side")

        # Check R data
        master_data = [self._get_field(r, 'rdata', 'data')
                       for r in self._get_field(master_tx, 'r_transactions') or []]
        master_data = [d for d in master_data if d is not None]
        slave_data = [self._get_field(r, 'rdata', 'data')
                      for r in self._get_field(slave_tx, 'r_transactions') or []]
        slave_data = [d for d in slave_data if d is not None]

        if len(master_data) != len(slave_data):
            mismatches.append(f"Data beat count: master={len(master_data)}, slave={len(slave_data)}")
        else:
            for i, (master_beat, slave_beat) in enumerate(zip(master_data, slave_data)):
                if master_beat != slave_beat:
                    mismatches.append(f"Data beat {i}: master=0x{master_beat:X}, slave=0x{slave_beat:X}")

        # Record result
        if mismatches:
            self.error_count += 1
            if self.log:
                self.log.error(f"Read transaction ID={id_value} has mismatches:")
                for mismatch in mismatches:
                    self.log.error(f"  {mismatch}")
        else:
            # Mark as matched
            master_tx['matched'] = True
            slave_tx['matched'] = True
            self.read_count += 1
            if self.log:
                self.log.debug(f"Read transaction ID={id_value} matched between master and slave")

    def report(self):
        """Generate comprehensive report of AXI4 transaction verification"""
        # Calculate unmatched transactions
        unmatched_writes = (
            len([tx for tx in self.master_writes.values() if not tx.get('matched', False)]) +
            len([tx for tx in self.slave_writes.values() if not tx.get('matched', False)])
        )

        unmatched_reads = (
            len([tx for tx in self.master_reads.values() if not tx.get('matched', False)]) +
            len([tx for tx in self.slave_reads.values() if not tx.get('matched', False)])
        )

        # Generate report
        report_lines = [
            f"{self.name} AXI4 Scoreboard Report",
            "-" * 50,
            f"Write transactions matched: {self.write_count}",
            f"Read transactions matched: {self.read_count}",
            f"Protocol errors: {self.protocol_error_count}",
            f"Data mismatches: {self.error_count}",
            f"Unmatched write transactions: {unmatched_writes}",
            f"Unmatched read transactions: {unmatched_reads}",
            "-" * 50,
            f"Total errors: {self.error_count + self.protocol_error_count + unmatched_writes + unmatched_reads}"
        ]

        report = "\n".join(report_lines)
        if self.log:
            self.log.info(report)

        return report

    def check_all_transactions_matched(self):
        """Check if all transactions have been matched"""
        # Check for unmatched writes
        unmatched_writes = (
            len([tx for tx in self.master_writes.values() if not tx.get('matched', False)]) +
            len([tx for tx in self.slave_writes.values() if not tx.get('matched', False)])
        )

        # Check for unmatched reads
        unmatched_reads = (
            len([tx for tx in self.master_reads.values() if not tx.get('matched', False)]) +
            len([tx for tx in self.slave_reads.values() if not tx.get('matched', False)])
        )

        # Return True if all matched
        return unmatched_writes == 0 and unmatched_reads == 0

    def clear(self):
        """Clear all transaction tracking and reset counters"""
        # Clear transaction tracking
        self.master_writes.clear()
        self.slave_writes.clear()
        self.master_reads.clear()
        self.slave_reads.clear()

        # Reset counters
        self.write_count = 0
        self.read_count = 0
        self.error_count = 0
        self.protocol_error_count = 0

        # Call parent clear
        super().clear()


class AXI4MemoryScoreboard(AXI4Scoreboard):
    """
    AXI4 scoreboard that uses a memory model for verification.

    This class extends the standard AXI4Scoreboard by:
    - Using a shared memory model as the "golden" reference
    - Verifying all memory operations against the model
    - Tracking out-of-order operations
    """

    def __init__(self, name, memory_model, id_width=8, addr_width=32, data_width=32, user_width=1, log=None):
        """
        Initialize AXI4 Memory Scoreboard.

        Args:
            name: Scoreboard name
            memory_model: Memory model to use as reference
            id_width: Width of ID fields (default: 8)
            addr_width: Width of address fields (default: 32)
            data_width: Width of data fields (default: 32)
            user_width: Width of user fields (default: 1)
            log: Logger instance
        """
        super().__init__(name, id_width, addr_width, data_width, user_width, log)

        # Store memory model
        self.memory_model = memory_model

        # Additional tracking for memory operations
        self.memory_writes = {}  # Write operations to memory
        self.memory_reads = {}   # Read operations from memory

    def add_write(self, addr, data, strb=None):
        """
        Add a memory write operation.

        Args:
            addr: Address to write to
            data: Data written
            strb: Write strobe mask (default: all enabled)
        """
        # Create a unique key for this operation
        op_id = len(self.memory_writes)
        timestamp = get_sim_time('ns')

        # Store operation
        self.memory_writes[op_id] = {
            'addr': addr,
            'data': data,
            'strb': strb if strb is not None else ((1 << (self.data_width // 8)) - 1),
            'time': timestamp,
            'verified': False
        }

        # Write to memory model if available
        if self.memory_model:
            try:
                # Convert data to bytearray
                data_bytes = self.memory_model.integer_to_bytearray(data, self.memory_model.bytes_per_line)

                # Write to memory
                self.memory_model.write(addr, data_bytes, strb)

                if self.log:
                    strb_str = f"0x{strb:X}" if strb is not None else "ALL"
                    self.log.debug(f"Memory write: addr=0x{addr:X}, data=0x{data:X}, strb={strb_str}")
            except Exception as e:
                if self.log:
                    self.log.error(f"Error writing to memory: {e}")

    def verify_read(self, addr, data):
        """
        Verify a memory read operation.

        Args:
            addr: Address read from
            data: Data returned

        Returns:
            bool: True if read data matches expected data
        """
        # Check against memory model
        if self.memory_model:
            try:
                # Read from memory
                expected_bytes = self.memory_model.read(addr, self.memory_model.bytes_per_line)
                expected = self.memory_model.bytearray_to_integer(expected_bytes)

                # Compare with actual data
                if expected != data:
                    if self.log:
                        self.log.error(f"Memory read mismatch: addr=0x{addr:X}, expected=0x{expected:X}, actual=0x{data:X}")
                    self.error_count += 1
                    return False
                else:
                    if self.log:
                        self.log.debug(f"Memory read verified: addr=0x{addr:X}, data=0x{data:X}")
                    return True
            except Exception as e:
                if self.log:
                    self.log.error(f"Error reading from memory: {e}")
                self.error_count += 1
                return False

        # No memory model to verify against
        return True

    def report(self):
        """Generate comprehensive report including memory operations"""
        # Get standard report
        std_report = super().report()

        # Add memory-specific information
        mem_report = [
            "",
            "Memory Operations",
            "-" * 50,
            f"Memory writes: {len(self.memory_writes)}",
            f"Memory reads: {len(self.memory_reads)}",
        ]

        # Return combined report
        return std_report + "\n" + "\n".join(mem_report)

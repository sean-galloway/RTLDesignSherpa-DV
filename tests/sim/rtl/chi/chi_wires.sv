// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 sean galloway
//
// Module: chi_wires
// Purpose: Zero-logic CHI link loopback for BFM-to-BFM simulation. Port names
//          are each side's OWN perspective (rn_rx* is what the RN-F drives,
//          hn_tx* is what the HN-F sees), so both BFMs bind with
//          dut_perspective=False. Wires only: no registers, no credits, no
//          protocol. The link layer, credits and protocol live in the BFMs.
//
// Subsystem: tests/sim
// Author: sean galloway
// Created: 2026-10-30

`timescale 1ns / 1ps

module chi_wires #(
    parameter int REQ_W = 137,
    parameter int RSP_W = 71,
    parameter int SNP_W = 94,
    parameter int DAT_W = 240
) (
    input  logic             clk,
    input  logic             rst_n,

    // ----- RN-F side ----------------------------------------------------
    // what the RN-F BFM drives (the far HN's rx) and samples (its tx)
    input  logic             rn_rxlinkactivereq,
    output logic             rn_rxlinkactiveack,
    input  logic             rn_rxsactive,
    input  logic             rn_rxreqflitpend,
    input  logic             rn_rxreqflitv,
    input  logic [REQ_W-1:0] rn_rxreqflit,
    output logic             rn_rxreqlcrdv,
    input  logic             rn_rxrspflitpend,
    input  logic             rn_rxrspflitv,
    input  logic [RSP_W-1:0] rn_rxrspflit,
    output logic             rn_rxrsplcrdv,
    input  logic             rn_rxdatflitpend,
    input  logic             rn_rxdatflitv,
    input  logic [DAT_W-1:0] rn_rxdatflit,
    output logic             rn_rxdatlcrdv,
    // what the RN-F BFM samples: RSP, DAT, SNP arriving from the HN
    output logic             rn_txlinkactivereq,
    input  logic             rn_txlinkactiveack,
    output logic             rn_txsactive,
    output logic             rn_txrspflitpend,
    output logic             rn_txrspflitv,
    output logic [RSP_W-1:0] rn_txrspflit,
    input  logic             rn_txrsplcrdv,
    output logic             rn_txdatflitpend,
    output logic             rn_txdatflitv,
    output logic [DAT_W-1:0] rn_txdatflit,
    input  logic             rn_txdatlcrdv,
    output logic             rn_txsnpflitpend,
    output logic             rn_txsnpflitv,
    output logic [SNP_W-1:0] rn_txsnpflit,
    input  logic             rn_txsnplcrdv,

    // ----- HN-F side ----------------------------------------------------
    // what the HN-F BFM drives (the far RN's rx) and samples (its tx)
    input  logic             hn_rxlinkactivereq,
    output logic             hn_rxlinkactiveack,
    input  logic             hn_rxsactive,
    input  logic             hn_rxrspflitpend,
    input  logic             hn_rxrspflitv,
    input  logic [RSP_W-1:0] hn_rxrspflit,
    output logic             hn_rxrsplcrdv,
    input  logic             hn_rxdatflitpend,
    input  logic             hn_rxdatflitv,
    input  logic [DAT_W-1:0] hn_rxdatflit,
    output logic             hn_rxdatlcrdv,
    input  logic             hn_rxsnpflitpend,
    input  logic             hn_rxsnpflitv,
    input  logic [SNP_W-1:0] hn_rxsnpflit,
    output logic             hn_rxsnplcrdv,
    // what the HN-F BFM samples: REQ, RSP, DAT arriving from the RN
    output logic             hn_txlinkactivereq,
    input  logic             hn_txlinkactiveack,
    output logic             hn_txsactive,
    output logic             hn_txreqflitpend,
    output logic             hn_txreqflitv,
    output logic [REQ_W-1:0] hn_txreqflit,
    input  logic             hn_txreqlcrdv,
    output logic             hn_txrspflitpend,
    output logic             hn_txrspflitv,
    output logic [RSP_W-1:0] hn_txrspflit,
    input  logic             hn_txrsplcrdv,
    output logic             hn_txdatflitpend,
    output logic             hn_txdatflitv,
    output logic [DAT_W-1:0] hn_txdatflit,
    input  logic             hn_txdatlcrdv
);

    /* verilator lint_off UNUSEDSIGNAL */
    logic unused_clk_rst;
    assign unused_clk_rst = clk ^ rst_n;
    /* verilator lint_on UNUSEDSIGNAL */

    // RN BFM drives rn_rx* -> HN BFM samples hn_tx*
    assign hn_txlinkactivereq = rn_rxlinkactivereq;
    assign rn_rxlinkactiveack = hn_txlinkactiveack;
    assign hn_txsactive       = rn_rxsactive;
    assign hn_txreqflitpend   = rn_rxreqflitpend;
    assign hn_txreqflitv      = rn_rxreqflitv;
    assign hn_txreqflit       = rn_rxreqflit;
    assign rn_rxreqlcrdv      = hn_txreqlcrdv;
    assign hn_txrspflitpend   = rn_rxrspflitpend;
    assign hn_txrspflitv      = rn_rxrspflitv;
    assign hn_txrspflit       = rn_rxrspflit;
    assign rn_rxrsplcrdv      = hn_txrsplcrdv;
    assign hn_txdatflitpend   = rn_rxdatflitpend;
    assign hn_txdatflitv      = rn_rxdatflitv;
    assign hn_txdatflit       = rn_rxdatflit;
    assign rn_rxdatlcrdv      = hn_txdatlcrdv;

    // HN BFM drives hn_rx* -> RN BFM samples rn_tx*
    assign rn_txlinkactivereq = hn_rxlinkactivereq;
    assign hn_rxlinkactiveack = rn_txlinkactiveack;
    assign rn_txsactive       = hn_rxsactive;
    assign rn_txrspflitpend   = hn_rxrspflitpend;
    assign rn_txrspflitv      = hn_rxrspflitv;
    assign rn_txrspflit       = hn_rxrspflit;
    assign hn_rxrsplcrdv      = rn_txrsplcrdv;
    assign rn_txdatflitpend   = hn_rxdatflitpend;
    assign rn_txdatflitv      = hn_rxdatflitv;
    assign rn_txdatflit       = hn_rxdatflit;
    assign hn_rxdatlcrdv      = rn_txdatlcrdv;
    assign rn_txsnpflitpend   = hn_rxsnpflitpend;
    assign rn_txsnpflitv      = hn_rxsnpflitv;
    assign rn_txsnpflit       = hn_rxsnpflit;
    assign hn_rxsnplcrdv      = rn_txsnplcrdv;

endmodule

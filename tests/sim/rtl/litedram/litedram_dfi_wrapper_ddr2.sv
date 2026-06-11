// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2024-2026 sean galloway
//
// DDR2 variant of litedram_dfi_wrapper — 2-phase DFI (1:2 gear).
// Same out-of-module reference pattern as the DDR3 wrapper, but with
// only phases 0 and 1 exposed.
//
// Generated from arty_ddr2_nocpu.yml. Widths: 13-bit address, 32-bit
// wrdata per phase, 4-bit wrdata_mask.

module litedram_dfi_wrapper_ddr2 (
    input  wire          clk,
    input  wire          sim_trace,
    output wire          init_done,
    output wire          init_error,
    output wire          user_clk,
    output wire          user_rst,

    input  wire   [23:0] user_port_wishbone_0_adr,
    input  wire  [127:0] user_port_wishbone_0_dat_w,
    input  wire   [15:0] user_port_wishbone_0_sel,
    input  wire          user_port_wishbone_0_cyc,
    input  wire          user_port_wishbone_0_stb,
    input  wire          user_port_wishbone_0_we,
    output wire  [127:0] user_port_wishbone_0_dat_r,
    output wire          user_port_wishbone_0_ack,
    output wire          user_port_wishbone_0_err,

    input  wire   [29:0] wb_ctrl_adr,
    input  wire   [31:0] wb_ctrl_dat_w,
    input  wire    [3:0] wb_ctrl_sel,
    input  wire          wb_ctrl_cyc,
    input  wire          wb_ctrl_stb,
    input  wire          wb_ctrl_we,
    input  wire    [2:0] wb_ctrl_cti,
    input  wire    [1:0] wb_ctrl_bte,
    output wire   [31:0] wb_ctrl_dat_r,
    output wire          wb_ctrl_ack,
    output wire          wb_ctrl_err,

    // 2-phase DFI
    output wire [12:0]   dfi_p0_address,
    output wire [2:0]    dfi_p0_bank,
    output wire          dfi_p0_cas_n,
    output wire          dfi_p0_cke,
    output wire          dfi_p0_cs_n,
    output wire          dfi_p0_odt,
    output wire          dfi_p0_ras_n,
    output wire          dfi_p0_reset_n,
    output wire          dfi_p0_we_n,
    output wire [31:0]   dfi_p0_wrdata,
    output wire          dfi_p0_wrdata_en,
    output wire [3:0]    dfi_p0_wrdata_mask,
    output wire [31:0]   dfi_p0_rddata,
    output wire          dfi_p0_rddata_en,
    output wire          dfi_p0_rddata_valid,

    output wire [12:0]   dfi_p1_address,
    output wire [2:0]    dfi_p1_bank,
    output wire          dfi_p1_cas_n,
    output wire          dfi_p1_cke,
    output wire          dfi_p1_cs_n,
    output wire          dfi_p1_odt,
    output wire          dfi_p1_ras_n,
    output wire          dfi_p1_reset_n,
    output wire          dfi_p1_we_n,
    output wire [31:0]   dfi_p1_wrdata,
    output wire          dfi_p1_wrdata_en,
    output wire [3:0]    dfi_p1_wrdata_mask,
    output wire [31:0]   dfi_p1_rddata,
    output wire          dfi_p1_rddata_en,
    output wire          dfi_p1_rddata_valid
);

    litedram_core inner (
        .clk        (clk),
        .sim_trace  (sim_trace),
        .init_done  (init_done),
        .init_error (init_error),
        .user_clk   (user_clk),
        .user_rst   (user_rst),

        .user_port_wishbone_0_adr  (user_port_wishbone_0_adr),
        .user_port_wishbone_0_dat_w(user_port_wishbone_0_dat_w),
        .user_port_wishbone_0_sel  (user_port_wishbone_0_sel),
        .user_port_wishbone_0_cyc  (user_port_wishbone_0_cyc),
        .user_port_wishbone_0_stb  (user_port_wishbone_0_stb),
        .user_port_wishbone_0_we   (user_port_wishbone_0_we),
        .user_port_wishbone_0_dat_r(user_port_wishbone_0_dat_r),
        .user_port_wishbone_0_ack  (user_port_wishbone_0_ack),
        .user_port_wishbone_0_err  (user_port_wishbone_0_err),

        .wb_ctrl_adr  (wb_ctrl_adr),
        .wb_ctrl_dat_w(wb_ctrl_dat_w),
        .wb_ctrl_sel  (wb_ctrl_sel),
        .wb_ctrl_cyc  (wb_ctrl_cyc),
        .wb_ctrl_stb  (wb_ctrl_stb),
        .wb_ctrl_we   (wb_ctrl_we),
        .wb_ctrl_cti  (wb_ctrl_cti),
        .wb_ctrl_bte  (wb_ctrl_bte),
        .wb_ctrl_dat_r(wb_ctrl_dat_r),
        .wb_ctrl_ack  (wb_ctrl_ack),
        .wb_ctrl_err  (wb_ctrl_err)
    );

    // Out-of-module DFI exposure (2-phase, no act_n for DDR2)
    assign dfi_p0_address      = inner.soc_litedramcore_master_p0_address;
    assign dfi_p0_bank         = inner.soc_litedramcore_master_p0_bank;
    assign dfi_p0_cas_n        = inner.soc_litedramcore_master_p0_cas_n;
    assign dfi_p0_cke          = inner.soc_litedramcore_master_p0_cke;
    assign dfi_p0_cs_n         = inner.soc_litedramcore_master_p0_cs_n;
    assign dfi_p0_odt          = inner.soc_litedramcore_master_p0_odt;
    assign dfi_p0_ras_n        = inner.soc_litedramcore_master_p0_ras_n;
    assign dfi_p0_reset_n      = inner.soc_litedramcore_master_p0_reset_n;
    assign dfi_p0_we_n         = inner.soc_litedramcore_master_p0_we_n;
    assign dfi_p0_wrdata       = inner.soc_litedramcore_master_p0_wrdata;
    assign dfi_p0_wrdata_en    = inner.soc_litedramcore_master_p0_wrdata_en;
    assign dfi_p0_wrdata_mask  = inner.soc_litedramcore_master_p0_wrdata_mask;
    assign dfi_p0_rddata       = inner.soc_litedramcore_master_p0_rddata;
    assign dfi_p0_rddata_en    = inner.soc_litedramcore_master_p0_rddata_en;
    assign dfi_p0_rddata_valid = inner.soc_litedramcore_master_p0_rddata_valid;

    assign dfi_p1_address      = inner.soc_litedramcore_master_p1_address;
    assign dfi_p1_bank         = inner.soc_litedramcore_master_p1_bank;
    assign dfi_p1_cas_n        = inner.soc_litedramcore_master_p1_cas_n;
    assign dfi_p1_cke          = inner.soc_litedramcore_master_p1_cke;
    assign dfi_p1_cs_n         = inner.soc_litedramcore_master_p1_cs_n;
    assign dfi_p1_odt          = inner.soc_litedramcore_master_p1_odt;
    assign dfi_p1_ras_n        = inner.soc_litedramcore_master_p1_ras_n;
    assign dfi_p1_reset_n      = inner.soc_litedramcore_master_p1_reset_n;
    assign dfi_p1_we_n         = inner.soc_litedramcore_master_p1_we_n;
    assign dfi_p1_wrdata       = inner.soc_litedramcore_master_p1_wrdata;
    assign dfi_p1_wrdata_en    = inner.soc_litedramcore_master_p1_wrdata_en;
    assign dfi_p1_wrdata_mask  = inner.soc_litedramcore_master_p1_wrdata_mask;
    assign dfi_p1_rddata       = inner.soc_litedramcore_master_p1_rddata;
    assign dfi_p1_rddata_en    = inner.soc_litedramcore_master_p1_rddata_en;
    assign dfi_p1_rddata_valid = inner.soc_litedramcore_master_p1_rddata_valid;

endmodule

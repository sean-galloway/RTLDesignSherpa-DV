// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2024-2026 sean galloway
//
// Wrapper around the generated LiteDRAM core that exposes the
// internal 4-phase DFI signals as proper top-level output ports.
// No --public-flat-rw, no cocotb hierarchy hacks — the wrapper
// uses SystemVerilog out-of-module references to grab the master_pN_*
// signals and surfaces them as ports.
//
// The wrapper is observation-only on the DFI side: it never drives
// signals INTO litedram_core. The MC's internal behavioral-PHY
// + behavioral-DRAM model still runs closed-loop (that's where
// LiteDRAM's writes/reads actually take effect); we just snapshot
// the DFI traffic for our DFI BFM slave to consume in parallel.
//
// Generated from tests/sim/rtl/litedram/arty_ddr3_nocpu.yml via
// regen.sh, --sim mode. Widths match that config (DDR3-800,
// MT41K128M16, 4-phase Xilinx 7-series ratio).

module litedram_dfi_wrapper (
    // ----- Clock + reset + status -----
    // --sim mode only exposes clk + sim_trace at the top of litedram_core
    // (no separate rst or pll_locked; the behavioral PHY model handles
    // those internally). user_rst/user_clk are clock-crossed outputs.
    input  wire          clk,
    input  wire          sim_trace,
    output wire          init_done,
    output wire          init_error,
    output wire          user_clk,
    output wire          user_rst,

    // ----- Wishbone host port (32-bit address, 128-bit data) -----
    input  wire   [23:0] user_port_wishbone_0_adr,
    input  wire  [127:0] user_port_wishbone_0_dat_w,
    input  wire   [15:0] user_port_wishbone_0_sel,
    input  wire          user_port_wishbone_0_cyc,
    input  wire          user_port_wishbone_0_stb,
    input  wire          user_port_wishbone_0_we,
    output wire  [127:0] user_port_wishbone_0_dat_r,
    output wire          user_port_wishbone_0_ack,
    output wire          user_port_wishbone_0_err,

    // ----- Wishbone CSR control port (typically tied off in cocotb) -----
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

    // ----- 4-phase DFI (PHY-facing; PHY→MC where applicable) -----
    // Phase 0
    output wire [13:0]   dfi_p0_address,
    output wire [2:0]    dfi_p0_bank,
    output wire          dfi_p0_act_n,
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
    // Phase 1
    output wire [13:0]   dfi_p1_address,
    output wire [2:0]    dfi_p1_bank,
    output wire          dfi_p1_act_n,
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
    output wire          dfi_p1_rddata_valid,
    // Phase 2
    output wire [13:0]   dfi_p2_address,
    output wire [2:0]    dfi_p2_bank,
    output wire          dfi_p2_act_n,
    output wire          dfi_p2_cas_n,
    output wire          dfi_p2_cke,
    output wire          dfi_p2_cs_n,
    output wire          dfi_p2_odt,
    output wire          dfi_p2_ras_n,
    output wire          dfi_p2_reset_n,
    output wire          dfi_p2_we_n,
    output wire [31:0]   dfi_p2_wrdata,
    output wire          dfi_p2_wrdata_en,
    output wire [3:0]    dfi_p2_wrdata_mask,
    output wire [31:0]   dfi_p2_rddata,
    output wire          dfi_p2_rddata_en,
    output wire          dfi_p2_rddata_valid,
    // Phase 3
    output wire [13:0]   dfi_p3_address,
    output wire [2:0]    dfi_p3_bank,
    output wire          dfi_p3_act_n,
    output wire          dfi_p3_cas_n,
    output wire          dfi_p3_cke,
    output wire          dfi_p3_cs_n,
    output wire          dfi_p3_odt,
    output wire          dfi_p3_ras_n,
    output wire          dfi_p3_reset_n,
    output wire          dfi_p3_we_n,
    output wire [31:0]   dfi_p3_wrdata,
    output wire          dfi_p3_wrdata_en,
    output wire [3:0]    dfi_p3_wrdata_mask,
    output wire [31:0]   dfi_p3_rddata,
    output wire          dfi_p3_rddata_en,
    output wire          dfi_p3_rddata_valid
);

    // ----- Instantiate the generated MC core -----
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

    // ----- Expose DFI via out-of-module references -----
    // Phase 0
    assign dfi_p0_address      = inner.soc_litedramcore_master_p0_address;
    assign dfi_p0_bank         = inner.soc_litedramcore_master_p0_bank;
    assign dfi_p0_act_n        = inner.soc_litedramcore_master_p0_act_n;
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
    // Phase 1
    assign dfi_p1_address      = inner.soc_litedramcore_master_p1_address;
    assign dfi_p1_bank         = inner.soc_litedramcore_master_p1_bank;
    assign dfi_p1_act_n        = inner.soc_litedramcore_master_p1_act_n;
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
    // Phase 2
    assign dfi_p2_address      = inner.soc_litedramcore_master_p2_address;
    assign dfi_p2_bank         = inner.soc_litedramcore_master_p2_bank;
    assign dfi_p2_act_n        = inner.soc_litedramcore_master_p2_act_n;
    assign dfi_p2_cas_n        = inner.soc_litedramcore_master_p2_cas_n;
    assign dfi_p2_cke          = inner.soc_litedramcore_master_p2_cke;
    assign dfi_p2_cs_n         = inner.soc_litedramcore_master_p2_cs_n;
    assign dfi_p2_odt          = inner.soc_litedramcore_master_p2_odt;
    assign dfi_p2_ras_n        = inner.soc_litedramcore_master_p2_ras_n;
    assign dfi_p2_reset_n      = inner.soc_litedramcore_master_p2_reset_n;
    assign dfi_p2_we_n         = inner.soc_litedramcore_master_p2_we_n;
    assign dfi_p2_wrdata       = inner.soc_litedramcore_master_p2_wrdata;
    assign dfi_p2_wrdata_en    = inner.soc_litedramcore_master_p2_wrdata_en;
    assign dfi_p2_wrdata_mask  = inner.soc_litedramcore_master_p2_wrdata_mask;
    assign dfi_p2_rddata       = inner.soc_litedramcore_master_p2_rddata;
    assign dfi_p2_rddata_en    = inner.soc_litedramcore_master_p2_rddata_en;
    assign dfi_p2_rddata_valid = inner.soc_litedramcore_master_p2_rddata_valid;
    // Phase 3
    assign dfi_p3_address      = inner.soc_litedramcore_master_p3_address;
    assign dfi_p3_bank         = inner.soc_litedramcore_master_p3_bank;
    assign dfi_p3_act_n        = inner.soc_litedramcore_master_p3_act_n;
    assign dfi_p3_cas_n        = inner.soc_litedramcore_master_p3_cas_n;
    assign dfi_p3_cke          = inner.soc_litedramcore_master_p3_cke;
    assign dfi_p3_cs_n         = inner.soc_litedramcore_master_p3_cs_n;
    assign dfi_p3_odt          = inner.soc_litedramcore_master_p3_odt;
    assign dfi_p3_ras_n        = inner.soc_litedramcore_master_p3_ras_n;
    assign dfi_p3_reset_n      = inner.soc_litedramcore_master_p3_reset_n;
    assign dfi_p3_we_n         = inner.soc_litedramcore_master_p3_we_n;
    assign dfi_p3_wrdata       = inner.soc_litedramcore_master_p3_wrdata;
    assign dfi_p3_wrdata_en    = inner.soc_litedramcore_master_p3_wrdata_en;
    assign dfi_p3_wrdata_mask  = inner.soc_litedramcore_master_p3_wrdata_mask;
    assign dfi_p3_rddata       = inner.soc_litedramcore_master_p3_rddata;
    assign dfi_p3_rddata_en    = inner.soc_litedramcore_master_p3_rddata_en;
    assign dfi_p3_rddata_valid = inner.soc_litedramcore_master_p3_rddata_valid;

endmodule

// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2024-2026 sean galloway
//
// Top-level harness for LiteDRAM ↔ DFI BFM slave co-sim.
//
// Wraps:
//   - litedram_dfi_wrapper (real MC + behavioral PHY/DRAM model)
//   - dfi_shim             (1-phase DFI passthrough used by all our
//                           BFM-based tests)
//
// The 4-phase DFI from LiteDRAM is exposed at the top as
// dfi_p[0..3]_* for a cocotb sampler coroutine to read each cycle.
// The sampler feeds DFIPhaseAdapter (gear=4); the adapter drives the
// shim's mc_dfi_* inputs; the shim's phy_dfi_* outputs feed
// DFISlavePHY (cocotb_bus.BusMonitor binding on phy_dfi prefix).
//
// Parameter widths match dfi_shim's defaults to keep DFISlavePHY's
// signal lookup happy.

module litedram_cosim_top #(
    parameter int ADDR_WIDTH        = 16,
    parameter int BANK_WIDTH        = 3,
    parameter int CS_WIDTH          = 1,
    parameter int CTRL_WIDTH        = 1,
    parameter int DATA_WIDTH        = 64,
    parameter int DATA_EN_WIDTH     = 1,
    parameter int DATA_MASK_BITS    = 8,
    parameter int RD_VALID_WIDTH    = 1,
    parameter int ERROR_INFO_WIDTH  = 8,
    parameter int TRAINING_PHASE_WIDTH = 3
) (
    // ----- LiteDRAM clock + status -----
    input  logic         clk,
    input  logic         dfi_rstn,
    input  logic         sim_trace,
    output logic         init_done,
    output logic         init_error,
    output logic         user_clk,
    output logic         user_rst,

    // ----- LiteDRAM Wishbone host port (128-bit) -----
    input  logic [23:0]  user_port_wishbone_0_adr,
    input  logic [127:0] user_port_wishbone_0_dat_w,
    input  logic [15:0]  user_port_wishbone_0_sel,
    input  logic         user_port_wishbone_0_cyc,
    input  logic         user_port_wishbone_0_stb,
    input  logic         user_port_wishbone_0_we,
    output logic [127:0] user_port_wishbone_0_dat_r,
    output logic         user_port_wishbone_0_ack,
    output logic         user_port_wishbone_0_err,

    // ----- LiteDRAM Wishbone CSR ctrl port (32-bit) -----
    input  logic [29:0]  wb_ctrl_adr,
    input  logic [31:0]  wb_ctrl_dat_w,
    input  logic [3:0]   wb_ctrl_sel,
    input  logic         wb_ctrl_cyc,
    input  logic         wb_ctrl_stb,
    input  logic         wb_ctrl_we,
    input  logic [2:0]   wb_ctrl_cti,
    input  logic [1:0]   wb_ctrl_bte,
    output logic [31:0]  wb_ctrl_dat_r,
    output logic         wb_ctrl_ack,
    output logic         wb_ctrl_err,

    // ----- 4-phase DFI from LiteDRAM (cocotb sampler reads) -----
    output logic [13:0]  dfi_p0_address, dfi_p1_address, dfi_p2_address, dfi_p3_address,
    output logic [2:0]   dfi_p0_bank,    dfi_p1_bank,    dfi_p2_bank,    dfi_p3_bank,
    output logic         dfi_p0_act_n,   dfi_p1_act_n,   dfi_p2_act_n,   dfi_p3_act_n,
    output logic         dfi_p0_cas_n,   dfi_p1_cas_n,   dfi_p2_cas_n,   dfi_p3_cas_n,
    output logic         dfi_p0_cke,     dfi_p1_cke,     dfi_p2_cke,     dfi_p3_cke,
    output logic         dfi_p0_cs_n,    dfi_p1_cs_n,    dfi_p2_cs_n,    dfi_p3_cs_n,
    output logic         dfi_p0_odt,     dfi_p1_odt,     dfi_p2_odt,     dfi_p3_odt,
    output logic         dfi_p0_ras_n,   dfi_p1_ras_n,   dfi_p2_ras_n,   dfi_p3_ras_n,
    output logic         dfi_p0_reset_n, dfi_p1_reset_n, dfi_p2_reset_n, dfi_p3_reset_n,
    output logic         dfi_p0_we_n,    dfi_p1_we_n,    dfi_p2_we_n,    dfi_p3_we_n,
    output logic [31:0]  dfi_p0_wrdata,  dfi_p1_wrdata,  dfi_p2_wrdata,  dfi_p3_wrdata,
    output logic         dfi_p0_wrdata_en, dfi_p1_wrdata_en,
                         dfi_p2_wrdata_en, dfi_p3_wrdata_en,
    output logic [3:0]   dfi_p0_wrdata_mask, dfi_p1_wrdata_mask,
                         dfi_p2_wrdata_mask, dfi_p3_wrdata_mask,
    output logic [31:0]  dfi_p0_rddata,  dfi_p1_rddata,  dfi_p2_rddata,  dfi_p3_rddata,
    output logic         dfi_p0_rddata_en, dfi_p1_rddata_en,
                         dfi_p2_rddata_en, dfi_p3_rddata_en,
    output logic         dfi_p0_rddata_valid, dfi_p1_rddata_valid,
                         dfi_p2_rddata_valid, dfi_p3_rddata_valid,

    // ----- 1-phase DFI MC-side (driven by DFIPhaseAdapter from Python) -----
    input  logic [ADDR_WIDTH-1:0]       mc_dfi_address,
    input  logic [BANK_WIDTH-1:0]       mc_dfi_bank,
    input  logic [CTRL_WIDTH-1:0]       mc_dfi_cas_n, mc_dfi_ras_n, mc_dfi_we_n,
    input  logic [CS_WIDTH-1:0]         mc_dfi_cs_n, mc_dfi_cke, mc_dfi_odt, mc_dfi_reset_n,
    input  logic [DATA_WIDTH-1:0]       mc_dfi_wrdata,
    input  logic [DATA_EN_WIDTH-1:0]    mc_dfi_wrdata_en, mc_dfi_rddata_en,
    input  logic [DATA_MASK_BITS-1:0]   mc_dfi_wrdata_mask,
    output logic [DATA_WIDTH-1:0]       mc_dfi_rddata,
    output logic [RD_VALID_WIDTH-1:0]   mc_dfi_rddata_valid,
    output logic [CTRL_WIDTH-1:0]       mc_dfi_error, mc_dfi_crc_alert,
    output logic [ERROR_INFO_WIDTH-1:0] mc_dfi_error_info,
    input  logic [CTRL_WIDTH-1:0]       mc_dfi_ctrlupd_req,
    output logic [CTRL_WIDTH-1:0]       mc_dfi_ctrlupd_ack, mc_dfi_phyupd_req,
    input  logic [CTRL_WIDTH-1:0]       mc_dfi_phyupd_ack,
    output logic [CTRL_WIDTH-1:0]       mc_dfi_training_active,
    output logic [TRAINING_PHASE_WIDTH-1:0] mc_dfi_training_phase,
    input  logic [CTRL_WIDTH-1:0]       mc_dfi_parity_in,
    output logic [CTRL_WIDTH-1:0]       mc_dfi_parity_check,
    input  logic [CTRL_WIDTH-1:0]       mc_dfi_freq_change_req,
    output logic [CTRL_WIDTH-1:0]       mc_dfi_freq_change_ack,
    input  logic [1:0]                  mc_dfi_freq_change_protocol,
    output logic [CTRL_WIDTH-1:0]       mc_dfi_disconnect_req,
    input  logic [CTRL_WIDTH-1:0]       mc_dfi_disconnect_ack,
    output logic [CTRL_WIDTH-1:0]       mc_dfi_phymstr_req,
    input  logic [CTRL_WIDTH-1:0]       mc_dfi_phymstr_ack,

    // ----- 1-phase DFI PHY-side (DFISlavePHY reads) -----
    output logic [ADDR_WIDTH-1:0]       phy_dfi_address,
    output logic [BANK_WIDTH-1:0]       phy_dfi_bank,
    output logic [CTRL_WIDTH-1:0]       phy_dfi_cas_n, phy_dfi_ras_n, phy_dfi_we_n,
    output logic [CS_WIDTH-1:0]         phy_dfi_cs_n, phy_dfi_cke, phy_dfi_odt, phy_dfi_reset_n,
    output logic [DATA_WIDTH-1:0]       phy_dfi_wrdata,
    output logic [DATA_EN_WIDTH-1:0]    phy_dfi_wrdata_en, phy_dfi_rddata_en,
    output logic [DATA_MASK_BITS-1:0]   phy_dfi_wrdata_mask,
    input  logic [DATA_WIDTH-1:0]       phy_dfi_rddata,
    input  logic [RD_VALID_WIDTH-1:0]   phy_dfi_rddata_valid,
    input  logic [CTRL_WIDTH-1:0]       phy_dfi_error, phy_dfi_crc_alert,
    input  logic [ERROR_INFO_WIDTH-1:0] phy_dfi_error_info,
    output logic [CTRL_WIDTH-1:0]       phy_dfi_ctrlupd_req,
    input  logic [CTRL_WIDTH-1:0]       phy_dfi_ctrlupd_ack, phy_dfi_phyupd_req,
    output logic [CTRL_WIDTH-1:0]       phy_dfi_phyupd_ack,
    input  logic [CTRL_WIDTH-1:0]       phy_dfi_training_active,
    input  logic [TRAINING_PHASE_WIDTH-1:0] phy_dfi_training_phase,
    output logic [CTRL_WIDTH-1:0]       phy_dfi_parity_in,
    input  logic [CTRL_WIDTH-1:0]       phy_dfi_parity_check,
    output logic [CTRL_WIDTH-1:0]       phy_dfi_freq_change_req,
    input  logic [CTRL_WIDTH-1:0]       phy_dfi_freq_change_ack,
    output logic [1:0]                  phy_dfi_freq_change_protocol,
    input  logic [CTRL_WIDTH-1:0]       phy_dfi_disconnect_req,
    output logic [CTRL_WIDTH-1:0]       phy_dfi_disconnect_ack,
    input  logic [CTRL_WIDTH-1:0]       phy_dfi_phymstr_req,
    output logic [CTRL_WIDTH-1:0]       phy_dfi_phymstr_ack
);

    // ===== LiteDRAM with 4-phase DFI exposed =====

    litedram_dfi_wrapper litedram_inst (
        .clk(clk), .sim_trace(sim_trace),
        .init_done(init_done), .init_error(init_error),
        .user_clk(user_clk), .user_rst(user_rst),
        .user_port_wishbone_0_adr(user_port_wishbone_0_adr),
        .user_port_wishbone_0_dat_w(user_port_wishbone_0_dat_w),
        .user_port_wishbone_0_sel(user_port_wishbone_0_sel),
        .user_port_wishbone_0_cyc(user_port_wishbone_0_cyc),
        .user_port_wishbone_0_stb(user_port_wishbone_0_stb),
        .user_port_wishbone_0_we(user_port_wishbone_0_we),
        .user_port_wishbone_0_dat_r(user_port_wishbone_0_dat_r),
        .user_port_wishbone_0_ack(user_port_wishbone_0_ack),
        .user_port_wishbone_0_err(user_port_wishbone_0_err),
        .wb_ctrl_adr(wb_ctrl_adr), .wb_ctrl_dat_w(wb_ctrl_dat_w),
        .wb_ctrl_sel(wb_ctrl_sel), .wb_ctrl_cyc(wb_ctrl_cyc),
        .wb_ctrl_stb(wb_ctrl_stb), .wb_ctrl_we(wb_ctrl_we),
        .wb_ctrl_cti(wb_ctrl_cti), .wb_ctrl_bte(wb_ctrl_bte),
        .wb_ctrl_dat_r(wb_ctrl_dat_r), .wb_ctrl_ack(wb_ctrl_ack),
        .wb_ctrl_err(wb_ctrl_err),
        // 4-phase DFI forwarded to top
        .dfi_p0_address(dfi_p0_address), .dfi_p0_bank(dfi_p0_bank),
        .dfi_p0_act_n(dfi_p0_act_n), .dfi_p0_cas_n(dfi_p0_cas_n),
        .dfi_p0_cke(dfi_p0_cke), .dfi_p0_cs_n(dfi_p0_cs_n),
        .dfi_p0_odt(dfi_p0_odt), .dfi_p0_ras_n(dfi_p0_ras_n),
        .dfi_p0_reset_n(dfi_p0_reset_n), .dfi_p0_we_n(dfi_p0_we_n),
        .dfi_p0_wrdata(dfi_p0_wrdata), .dfi_p0_wrdata_en(dfi_p0_wrdata_en),
        .dfi_p0_wrdata_mask(dfi_p0_wrdata_mask),
        .dfi_p0_rddata(dfi_p0_rddata), .dfi_p0_rddata_en(dfi_p0_rddata_en),
        .dfi_p0_rddata_valid(dfi_p0_rddata_valid),
        .dfi_p1_address(dfi_p1_address), .dfi_p1_bank(dfi_p1_bank),
        .dfi_p1_act_n(dfi_p1_act_n), .dfi_p1_cas_n(dfi_p1_cas_n),
        .dfi_p1_cke(dfi_p1_cke), .dfi_p1_cs_n(dfi_p1_cs_n),
        .dfi_p1_odt(dfi_p1_odt), .dfi_p1_ras_n(dfi_p1_ras_n),
        .dfi_p1_reset_n(dfi_p1_reset_n), .dfi_p1_we_n(dfi_p1_we_n),
        .dfi_p1_wrdata(dfi_p1_wrdata), .dfi_p1_wrdata_en(dfi_p1_wrdata_en),
        .dfi_p1_wrdata_mask(dfi_p1_wrdata_mask),
        .dfi_p1_rddata(dfi_p1_rddata), .dfi_p1_rddata_en(dfi_p1_rddata_en),
        .dfi_p1_rddata_valid(dfi_p1_rddata_valid),
        .dfi_p2_address(dfi_p2_address), .dfi_p2_bank(dfi_p2_bank),
        .dfi_p2_act_n(dfi_p2_act_n), .dfi_p2_cas_n(dfi_p2_cas_n),
        .dfi_p2_cke(dfi_p2_cke), .dfi_p2_cs_n(dfi_p2_cs_n),
        .dfi_p2_odt(dfi_p2_odt), .dfi_p2_ras_n(dfi_p2_ras_n),
        .dfi_p2_reset_n(dfi_p2_reset_n), .dfi_p2_we_n(dfi_p2_we_n),
        .dfi_p2_wrdata(dfi_p2_wrdata), .dfi_p2_wrdata_en(dfi_p2_wrdata_en),
        .dfi_p2_wrdata_mask(dfi_p2_wrdata_mask),
        .dfi_p2_rddata(dfi_p2_rddata), .dfi_p2_rddata_en(dfi_p2_rddata_en),
        .dfi_p2_rddata_valid(dfi_p2_rddata_valid),
        .dfi_p3_address(dfi_p3_address), .dfi_p3_bank(dfi_p3_bank),
        .dfi_p3_act_n(dfi_p3_act_n), .dfi_p3_cas_n(dfi_p3_cas_n),
        .dfi_p3_cke(dfi_p3_cke), .dfi_p3_cs_n(dfi_p3_cs_n),
        .dfi_p3_odt(dfi_p3_odt), .dfi_p3_ras_n(dfi_p3_ras_n),
        .dfi_p3_reset_n(dfi_p3_reset_n), .dfi_p3_we_n(dfi_p3_we_n),
        .dfi_p3_wrdata(dfi_p3_wrdata), .dfi_p3_wrdata_en(dfi_p3_wrdata_en),
        .dfi_p3_wrdata_mask(dfi_p3_wrdata_mask),
        .dfi_p3_rddata(dfi_p3_rddata), .dfi_p3_rddata_en(dfi_p3_rddata_en),
        .dfi_p3_rddata_valid(dfi_p3_rddata_valid)
    );

    // ===== 1-phase passthrough shim (so DFISlavePHY can bind) =====

    dfi_shim #(
        .ADDR_WIDTH(ADDR_WIDTH),
        .BANK_WIDTH(BANK_WIDTH),
        .CS_WIDTH(CS_WIDTH),
        .CTRL_WIDTH(CTRL_WIDTH),
        .DATA_WIDTH(DATA_WIDTH),
        .DATA_EN_WIDTH(DATA_EN_WIDTH),
        .DATA_MASK_BITS(DATA_MASK_BITS),
        .RD_VALID_WIDTH(RD_VALID_WIDTH),
        .ERROR_INFO_WIDTH(ERROR_INFO_WIDTH),
        .TRAINING_PHASE_WIDTH(TRAINING_PHASE_WIDTH)
    ) shim_inst (
        .dfi_clk(clk), .dfi_rstn(dfi_rstn),
        // MC-facing
        .mc_dfi_address(mc_dfi_address), .mc_dfi_bank(mc_dfi_bank),
        .mc_dfi_cas_n(mc_dfi_cas_n), .mc_dfi_ras_n(mc_dfi_ras_n),
        .mc_dfi_we_n(mc_dfi_we_n), .mc_dfi_cs_n(mc_dfi_cs_n),
        .mc_dfi_cke(mc_dfi_cke), .mc_dfi_odt(mc_dfi_odt),
        .mc_dfi_reset_n(mc_dfi_reset_n),
        .mc_dfi_wrdata(mc_dfi_wrdata), .mc_dfi_wrdata_en(mc_dfi_wrdata_en),
        .mc_dfi_wrdata_mask(mc_dfi_wrdata_mask),
        .mc_dfi_rddata_en(mc_dfi_rddata_en),
        .mc_dfi_rddata(mc_dfi_rddata), .mc_dfi_rddata_valid(mc_dfi_rddata_valid),
        .mc_dfi_error(mc_dfi_error), .mc_dfi_error_info(mc_dfi_error_info),
        .mc_dfi_crc_alert(mc_dfi_crc_alert),
        .mc_dfi_ctrlupd_req(mc_dfi_ctrlupd_req),
        .mc_dfi_ctrlupd_ack(mc_dfi_ctrlupd_ack),
        .mc_dfi_phyupd_req(mc_dfi_phyupd_req),
        .mc_dfi_phyupd_ack(mc_dfi_phyupd_ack),
        .mc_dfi_training_active(mc_dfi_training_active),
        .mc_dfi_training_phase(mc_dfi_training_phase),
        .mc_dfi_parity_in(mc_dfi_parity_in),
        .mc_dfi_parity_check(mc_dfi_parity_check),
        .mc_dfi_freq_change_req(mc_dfi_freq_change_req),
        .mc_dfi_freq_change_ack(mc_dfi_freq_change_ack),
        .mc_dfi_freq_change_protocol(mc_dfi_freq_change_protocol),
        .mc_dfi_disconnect_req(mc_dfi_disconnect_req),
        .mc_dfi_disconnect_ack(mc_dfi_disconnect_ack),
        .mc_dfi_phymstr_req(mc_dfi_phymstr_req),
        .mc_dfi_phymstr_ack(mc_dfi_phymstr_ack),
        // PHY-facing
        .phy_dfi_address(phy_dfi_address), .phy_dfi_bank(phy_dfi_bank),
        .phy_dfi_cas_n(phy_dfi_cas_n), .phy_dfi_ras_n(phy_dfi_ras_n),
        .phy_dfi_we_n(phy_dfi_we_n), .phy_dfi_cs_n(phy_dfi_cs_n),
        .phy_dfi_cke(phy_dfi_cke), .phy_dfi_odt(phy_dfi_odt),
        .phy_dfi_reset_n(phy_dfi_reset_n),
        .phy_dfi_wrdata(phy_dfi_wrdata), .phy_dfi_wrdata_en(phy_dfi_wrdata_en),
        .phy_dfi_wrdata_mask(phy_dfi_wrdata_mask),
        .phy_dfi_rddata_en(phy_dfi_rddata_en),
        .phy_dfi_rddata(phy_dfi_rddata), .phy_dfi_rddata_valid(phy_dfi_rddata_valid),
        .phy_dfi_error(phy_dfi_error), .phy_dfi_error_info(phy_dfi_error_info),
        .phy_dfi_crc_alert(phy_dfi_crc_alert),
        .phy_dfi_ctrlupd_req(phy_dfi_ctrlupd_req),
        .phy_dfi_ctrlupd_ack(phy_dfi_ctrlupd_ack),
        .phy_dfi_phyupd_req(phy_dfi_phyupd_req),
        .phy_dfi_phyupd_ack(phy_dfi_phyupd_ack),
        .phy_dfi_training_active(phy_dfi_training_active),
        .phy_dfi_training_phase(phy_dfi_training_phase),
        .phy_dfi_parity_in(phy_dfi_parity_in),
        .phy_dfi_parity_check(phy_dfi_parity_check),
        .phy_dfi_freq_change_req(phy_dfi_freq_change_req),
        .phy_dfi_freq_change_ack(phy_dfi_freq_change_ack),
        .phy_dfi_freq_change_protocol(phy_dfi_freq_change_protocol),
        .phy_dfi_disconnect_req(phy_dfi_disconnect_req),
        .phy_dfi_disconnect_ack(phy_dfi_disconnect_ack),
        .phy_dfi_phymstr_req(phy_dfi_phymstr_req),
        .phy_dfi_phymstr_ack(phy_dfi_phymstr_ack)
    );

endmodule

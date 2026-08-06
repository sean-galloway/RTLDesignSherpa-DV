// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2024-2026 sean galloway
//
// DFI wire shim — passthrough between an MC-side BFM and a PHY-side
// BFM. The shim has no logic; it lets us attach two monitors (one on each
// side) and verify they see the same packets, exercising the real cocotb
// signal-binding path without a behavioral loopback.
//
// Signal set is spec-verified (DFI v2.1.1-v4.0 signal tables): the
// command/write/read trio plus the real handshake wires — update
// (bidirectional incl. phyupd_type), status (init_start/init_complete
// carrying the frequency-change protocol, freq_ratio, the v4.0
// frequency indicator), training en/req/resp handshakes, low power,
// error interface, dfi_alert_n, the v2.1 dfi_parity_error, the v4.0
// disconnect_error flag, and the PHY Master req/ack pair.

module dfi_shim #(
    parameter int ADDR_WIDTH     = 16,
    parameter int BANK_WIDTH     = 3,
    parameter int CS_WIDTH       = 1,
    parameter int CTRL_WIDTH     = 1,
    parameter int DATA_WIDTH     = 64,
    parameter int DATA_EN_WIDTH  = 1,
    parameter int DATA_MASK_BITS = 8,    // data_width / 8
    parameter int RD_VALID_WIDTH = 1,
    parameter int ERROR_INFO_WIDTH = 8,  // v3.0+ error sub-interface code width
    parameter int FREQ_WIDTH     = 5,    // v4.0 dfi_frequency indicator
    parameter int LP_WAKEUP_WIDTH = 4    // dfi_lp_wakeup encoding
) (
    input  logic dfi_clk,
    input  logic dfi_rstn,

    // ----- MC-facing port -----
    // Command sub-interface (MC drives)
    input  logic [ADDR_WIDTH-1:0]     mc_dfi_address,
    input  logic [BANK_WIDTH-1:0]     mc_dfi_bank,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_cas_n,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_ras_n,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_we_n,
    input  logic [CS_WIDTH-1:0]       mc_dfi_cs_n,
    input  logic [CS_WIDTH-1:0]       mc_dfi_cke,
    input  logic [CS_WIDTH-1:0]       mc_dfi_odt,
    input  logic [CS_WIDTH-1:0]       mc_dfi_reset_n,
    // Write data sub-interface (MC drives)
    input  logic [DATA_WIDTH-1:0]     mc_dfi_wrdata,
    input  logic [DATA_EN_WIDTH-1:0]  mc_dfi_wrdata_en,
    input  logic [DATA_MASK_BITS-1:0] mc_dfi_wrdata_mask,
    // Read data sub-interface (rddata_en is MC-driven; rddata/_valid are PHY-driven)
    input  logic [DATA_EN_WIDTH-1:0]  mc_dfi_rddata_en,
    output logic [DATA_WIDTH-1:0]     mc_dfi_rddata,
    output logic [RD_VALID_WIDTH-1:0] mc_dfi_rddata_valid,
    // Error sub-interface (PHY drives; v3.0+)
    output logic [CTRL_WIDTH-1:0]     mc_dfi_error,
    output logic [ERROR_INFO_WIDTH-1:0] mc_dfi_error_info,
    // Alert (PHY drives; v3.0+, ACTIVE LOW; CRC + CA parity)
    output logic [CTRL_WIDTH-1:0]     mc_dfi_alert_n,
    // Update interface — MC-initiated (MC drives req, PHY acks)
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_ctrlupd_req,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_ctrlupd_ack,
    // Update interface — PHY-initiated (PHY drives req+type, MC acks)
    output logic [CTRL_WIDTH-1:0]     mc_dfi_phyupd_req,
    output logic [1:0]                mc_dfi_phyupd_type,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_phyupd_ack,
    // Training interface (v2.1-v4.0: MC drives enables, PHY requests/responds)
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_rdlvl_en,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_rdlvl_gate_en,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_wrlvl_en,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_rdlvl_req,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_rdlvl_gate_req,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_wrlvl_req,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_rdlvl_resp,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_wrlvl_resp,
    // CA parity (MC drives parity_in; PHY drives parity_error — v2.1 wire)
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_parity_in,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_parity_error,
    // Status interface (MC drives init_start/ratio/frequency; PHY drives init_complete)
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_init_start,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_init_complete,
    input  logic [1:0]                mc_dfi_freq_ratio,
    input  logic [FREQ_WIDTH-1:0]     mc_dfi_frequency,
    // Low power control (MC drives requests + wakeup; PHY acks)
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_lp_ctrl_req,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_lp_data_req,
    input  logic [LP_WAKEUP_WIDTH-1:0] mc_dfi_lp_wakeup,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_lp_ack,
    // Disconnect Protocol (v4.0+; MC drives the QOS/error flag)
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_disconnect_error,
    // PHY Master Interface (v4.0; PHY drives req, MC acks)
    output logic [CTRL_WIDTH-1:0]     mc_dfi_phymstr_req,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_phymstr_ack,

    // ----- PHY-facing port -----
    // Command sub-interface (PHY observes)
    output logic [ADDR_WIDTH-1:0]     phy_dfi_address,
    output logic [BANK_WIDTH-1:0]     phy_dfi_bank,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_cas_n,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_ras_n,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_we_n,
    output logic [CS_WIDTH-1:0]       phy_dfi_cs_n,
    output logic [CS_WIDTH-1:0]       phy_dfi_cke,
    output logic [CS_WIDTH-1:0]       phy_dfi_odt,
    output logic [CS_WIDTH-1:0]       phy_dfi_reset_n,
    // Write data sub-interface (PHY observes)
    output logic [DATA_WIDTH-1:0]     phy_dfi_wrdata,
    output logic [DATA_EN_WIDTH-1:0]  phy_dfi_wrdata_en,
    output logic [DATA_MASK_BITS-1:0] phy_dfi_wrdata_mask,
    // Read data sub-interface (rddata_en observed; rddata/_valid driven by PHY)
    output logic [DATA_EN_WIDTH-1:0]  phy_dfi_rddata_en,
    input  logic [DATA_WIDTH-1:0]     phy_dfi_rddata,
    input  logic [RD_VALID_WIDTH-1:0] phy_dfi_rddata_valid,
    // Error sub-interface (PHY drives)
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_error,
    input  logic [ERROR_INFO_WIDTH-1:0] phy_dfi_error_info,
    // Alert mirror (PHY drives)
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_alert_n,
    // Update interface mirrors
    output logic [CTRL_WIDTH-1:0]     phy_dfi_ctrlupd_req,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_ctrlupd_ack,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_phyupd_req,
    input  logic [1:0]                phy_dfi_phyupd_type,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_phyupd_ack,
    // Training interface mirrors
    output logic [CTRL_WIDTH-1:0]     phy_dfi_rdlvl_en,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_rdlvl_gate_en,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_wrlvl_en,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_rdlvl_req,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_rdlvl_gate_req,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_wrlvl_req,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_rdlvl_resp,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_wrlvl_resp,
    // CA parity mirrors
    output logic [CTRL_WIDTH-1:0]     phy_dfi_parity_in,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_parity_error,
    // Status mirrors
    output logic [CTRL_WIDTH-1:0]     phy_dfi_init_start,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_init_complete,
    output logic [1:0]                phy_dfi_freq_ratio,
    output logic [FREQ_WIDTH-1:0]     phy_dfi_frequency,
    // Low power mirrors
    output logic [CTRL_WIDTH-1:0]     phy_dfi_lp_ctrl_req,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_lp_data_req,
    output logic [LP_WAKEUP_WIDTH-1:0] phy_dfi_lp_wakeup,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_lp_ack,
    // Disconnect mirror
    output logic [CTRL_WIDTH-1:0]     phy_dfi_disconnect_error,
    // PHY Master mirror
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_phymstr_req,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_phymstr_ack
);

    // ----- MC → PHY -----
    assign phy_dfi_address       = mc_dfi_address;
    assign phy_dfi_bank          = mc_dfi_bank;
    assign phy_dfi_cas_n         = mc_dfi_cas_n;
    assign phy_dfi_ras_n         = mc_dfi_ras_n;
    assign phy_dfi_we_n          = mc_dfi_we_n;
    assign phy_dfi_cs_n          = mc_dfi_cs_n;
    assign phy_dfi_cke           = mc_dfi_cke;
    assign phy_dfi_odt           = mc_dfi_odt;
    assign phy_dfi_reset_n       = mc_dfi_reset_n;
    assign phy_dfi_wrdata        = mc_dfi_wrdata;
    assign phy_dfi_wrdata_en     = mc_dfi_wrdata_en;
    assign phy_dfi_wrdata_mask   = mc_dfi_wrdata_mask;
    assign phy_dfi_rddata_en     = mc_dfi_rddata_en;
    assign phy_dfi_ctrlupd_req   = mc_dfi_ctrlupd_req;
    assign phy_dfi_phyupd_ack    = mc_dfi_phyupd_ack;
    assign phy_dfi_rdlvl_en      = mc_dfi_rdlvl_en;
    assign phy_dfi_rdlvl_gate_en = mc_dfi_rdlvl_gate_en;
    assign phy_dfi_wrlvl_en      = mc_dfi_wrlvl_en;
    assign phy_dfi_parity_in     = mc_dfi_parity_in;
    assign phy_dfi_init_start    = mc_dfi_init_start;
    assign phy_dfi_freq_ratio    = mc_dfi_freq_ratio;
    assign phy_dfi_frequency     = mc_dfi_frequency;
    assign phy_dfi_lp_ctrl_req   = mc_dfi_lp_ctrl_req;
    assign phy_dfi_lp_data_req   = mc_dfi_lp_data_req;
    assign phy_dfi_lp_wakeup     = mc_dfi_lp_wakeup;
    assign phy_dfi_disconnect_error = mc_dfi_disconnect_error;
    assign phy_dfi_phymstr_ack   = mc_dfi_phymstr_ack;

    // ----- PHY → MC -----
    assign mc_dfi_rddata         = phy_dfi_rddata;
    assign mc_dfi_rddata_valid   = phy_dfi_rddata_valid;
    assign mc_dfi_error          = phy_dfi_error;
    assign mc_dfi_error_info     = phy_dfi_error_info;
    assign mc_dfi_alert_n        = phy_dfi_alert_n;
    assign mc_dfi_ctrlupd_ack    = phy_dfi_ctrlupd_ack;
    assign mc_dfi_phyupd_req     = phy_dfi_phyupd_req;
    assign mc_dfi_phyupd_type    = phy_dfi_phyupd_type;
    assign mc_dfi_rdlvl_req      = phy_dfi_rdlvl_req;
    assign mc_dfi_rdlvl_gate_req = phy_dfi_rdlvl_gate_req;
    assign mc_dfi_wrlvl_req      = phy_dfi_wrlvl_req;
    assign mc_dfi_rdlvl_resp     = phy_dfi_rdlvl_resp;
    assign mc_dfi_wrlvl_resp     = phy_dfi_wrlvl_resp;
    assign mc_dfi_parity_error   = phy_dfi_parity_error;
    assign mc_dfi_init_complete  = phy_dfi_init_complete;
    assign mc_dfi_lp_ack         = phy_dfi_lp_ack;
    assign mc_dfi_phymstr_req    = phy_dfi_phymstr_req;

endmodule

// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2024-2026 sean galloway
//
// DFI v5.x/v6.0 wire shim — passthrough for the DDR5/LPDDR5-era
// sub-interfaces that the legacy dfi_shim (v2.1-v4.0 signal set)
// doesn't carry: PHY Managed (the v5.2 dfi_phymngd_* rename), WCK
// control, the MC-to-PHY message channel, split frequency ratios +
// FSP, the split low-power wires, 2N mode, and the v6.0 renames
// (dfi_alert, dfi_phy_error/_info, dfi_sleep). Signal names are
// spec-verified against the v5.2 / v6.0 books (dfi_signal_catalog).
//
// Both the v5.x names and the v6.0 renames are present so one shim
// serves both behavior classes; a test drives whichever era's wires
// its stack samples.

module dfi_shim_v5 #(
    parameter int CTRL_WIDTH   = 1,
    parameter int CS_WIDTH     = 1,
    parameter int FREQ_WIDTH   = 6,   // dfi_frequency (up to 6 bits in v5.x+)
    parameter int RATIO_WIDTH  = 3,   // cmd/data freq ratio (3 bits in v6.0)
    parameter int WCK_WIDTH    = 2,   // wck_en / wck_cs per slice
    parameter int WCK_TOGGLE_WIDTH = 4,
    parameter int MSG_WIDTH    = 8,   // dfi_ctrlmsg opcode
    parameter int MSG_DATA_WIDTH = 16,
    parameter int ERROR_INFO_WIDTH = 8,
    parameter int LP_WAKEUP_WIDTH = 3
) (
    input  logic dfi_clk,
    input  logic dfi_rstn,

    // ----- MC-facing port -----
    // Status: init handshake + v5.2 split ratios + FSP + indicator
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_init_start,
    output logic [CTRL_WIDTH-1:0]      mc_dfi_init_complete,
    input  logic [RATIO_WIDTH-1:0]     mc_dfi_cmd_freq_ratio,
    input  logic [RATIO_WIDTH-1:0]     mc_dfi_data_freq_ratio,
    input  logic [1:0]                 mc_dfi_freq_fsp,
    input  logic [FREQ_WIDTH-1:0]      mc_dfi_frequency,
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_sleep,          // v6.0
    // Command-era extras
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_2n_mode,
    output logic [CTRL_WIDTH-1:0]      mc_dfi_alert_n,        // v5.x
    output logic [CTRL_WIDTH-1:0]      mc_dfi_alert,          // v6.0
    // PHY Managed (v5.2 rename of PHY Master)
    output logic [CTRL_WIDTH-1:0]      mc_dfi_phymngd_req,
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_phymngd_ack,
    output logic [CS_WIDTH-1:0]        mc_dfi_phymngd_cs_state,
    output logic [CTRL_WIDTH-1:0]      mc_dfi_phymngd_state_sel,
    output logic [1:0]                 mc_dfi_phymngd_type,
    // Disconnect (v5.x only; removed in v6.0)
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_disconnect_error,
    // MC-to-PHY message interface
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_ctrlmsg_req,
    output logic [CTRL_WIDTH-1:0]      mc_dfi_ctrlmsg_ack,
    input  logic [MSG_WIDTH-1:0]       mc_dfi_ctrlmsg,
    input  logic [MSG_DATA_WIDTH-1:0]  mc_dfi_ctrlmsg_data,
    // WCK control (LPDDR5/LPDDR6)
    input  logic [WCK_WIDTH-1:0]       mc_dfi_wck_en,
    input  logic [WCK_TOGGLE_WIDTH-1:0] mc_dfi_wck_toggle,
    input  logic [WCK_WIDTH-1:0]       mc_dfi_wck_cs,
    // Error interface: v5.x names + v6.0 renames
    output logic [CTRL_WIDTH-1:0]      mc_dfi_error,
    output logic [ERROR_INFO_WIDTH-1:0] mc_dfi_error_info,
    output logic [CTRL_WIDTH-1:0]      mc_dfi_phy_error,
    output logic [ERROR_INFO_WIDTH-1:0] mc_dfi_phy_error_info,
    // Low power (5.1 split acks/wakeups)
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_lp_ctrl_req,
    input  logic [CTRL_WIDTH-1:0]      mc_dfi_lp_data_req,
    input  logic [LP_WAKEUP_WIDTH-1:0] mc_dfi_lp_ctrl_wakeup,
    input  logic [LP_WAKEUP_WIDTH-1:0] mc_dfi_lp_data_wakeup,
    output logic [CTRL_WIDTH-1:0]      mc_dfi_lp_ctrl_ack,
    output logic [CTRL_WIDTH-1:0]      mc_dfi_lp_data_ack,

    // ----- PHY-facing port (mirror) -----
    output logic [CTRL_WIDTH-1:0]      phy_dfi_init_start,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_init_complete,
    output logic [RATIO_WIDTH-1:0]     phy_dfi_cmd_freq_ratio,
    output logic [RATIO_WIDTH-1:0]     phy_dfi_data_freq_ratio,
    output logic [1:0]                 phy_dfi_freq_fsp,
    output logic [FREQ_WIDTH-1:0]      phy_dfi_frequency,
    output logic [CTRL_WIDTH-1:0]      phy_dfi_sleep,
    output logic [CTRL_WIDTH-1:0]      phy_dfi_2n_mode,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_alert_n,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_alert,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_phymngd_req,
    output logic [CTRL_WIDTH-1:0]      phy_dfi_phymngd_ack,
    input  logic [CS_WIDTH-1:0]        phy_dfi_phymngd_cs_state,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_phymngd_state_sel,
    input  logic [1:0]                 phy_dfi_phymngd_type,
    output logic [CTRL_WIDTH-1:0]      phy_dfi_disconnect_error,
    output logic [CTRL_WIDTH-1:0]      phy_dfi_ctrlmsg_req,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_ctrlmsg_ack,
    output logic [MSG_WIDTH-1:0]       phy_dfi_ctrlmsg,
    output logic [MSG_DATA_WIDTH-1:0]  phy_dfi_ctrlmsg_data,
    output logic [WCK_WIDTH-1:0]       phy_dfi_wck_en,
    output logic [WCK_TOGGLE_WIDTH-1:0] phy_dfi_wck_toggle,
    output logic [WCK_WIDTH-1:0]       phy_dfi_wck_cs,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_error,
    input  logic [ERROR_INFO_WIDTH-1:0] phy_dfi_error_info,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_phy_error,
    input  logic [ERROR_INFO_WIDTH-1:0] phy_dfi_phy_error_info,
    output logic [CTRL_WIDTH-1:0]      phy_dfi_lp_ctrl_req,
    output logic [CTRL_WIDTH-1:0]      phy_dfi_lp_data_req,
    output logic [LP_WAKEUP_WIDTH-1:0] phy_dfi_lp_ctrl_wakeup,
    output logic [LP_WAKEUP_WIDTH-1:0] phy_dfi_lp_data_wakeup,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_lp_ctrl_ack,
    input  logic [CTRL_WIDTH-1:0]      phy_dfi_lp_data_ack
);

    // MC → PHY
    assign phy_dfi_init_start      = mc_dfi_init_start;
    assign phy_dfi_cmd_freq_ratio  = mc_dfi_cmd_freq_ratio;
    assign phy_dfi_data_freq_ratio = mc_dfi_data_freq_ratio;
    assign phy_dfi_freq_fsp        = mc_dfi_freq_fsp;
    assign phy_dfi_frequency       = mc_dfi_frequency;
    assign phy_dfi_sleep           = mc_dfi_sleep;
    assign phy_dfi_2n_mode         = mc_dfi_2n_mode;
    assign phy_dfi_phymngd_ack     = mc_dfi_phymngd_ack;
    assign phy_dfi_disconnect_error = mc_dfi_disconnect_error;
    assign phy_dfi_ctrlmsg_req     = mc_dfi_ctrlmsg_req;
    assign phy_dfi_ctrlmsg         = mc_dfi_ctrlmsg;
    assign phy_dfi_ctrlmsg_data    = mc_dfi_ctrlmsg_data;
    assign phy_dfi_wck_en          = mc_dfi_wck_en;
    assign phy_dfi_wck_toggle      = mc_dfi_wck_toggle;
    assign phy_dfi_wck_cs          = mc_dfi_wck_cs;
    assign phy_dfi_lp_ctrl_req     = mc_dfi_lp_ctrl_req;
    assign phy_dfi_lp_data_req     = mc_dfi_lp_data_req;
    assign phy_dfi_lp_ctrl_wakeup  = mc_dfi_lp_ctrl_wakeup;
    assign phy_dfi_lp_data_wakeup  = mc_dfi_lp_data_wakeup;

    // PHY → MC
    assign mc_dfi_init_complete    = phy_dfi_init_complete;
    assign mc_dfi_alert_n          = phy_dfi_alert_n;
    assign mc_dfi_alert            = phy_dfi_alert;
    assign mc_dfi_phymngd_req      = phy_dfi_phymngd_req;
    assign mc_dfi_phymngd_cs_state = phy_dfi_phymngd_cs_state;
    assign mc_dfi_phymngd_state_sel = phy_dfi_phymngd_state_sel;
    assign mc_dfi_phymngd_type     = phy_dfi_phymngd_type;
    assign mc_dfi_ctrlmsg_ack      = phy_dfi_ctrlmsg_ack;
    assign mc_dfi_error            = phy_dfi_error;
    assign mc_dfi_error_info       = phy_dfi_error_info;
    assign mc_dfi_phy_error        = phy_dfi_phy_error;
    assign mc_dfi_phy_error_info   = phy_dfi_phy_error_info;
    assign mc_dfi_lp_ctrl_ack      = phy_dfi_lp_ctrl_ack;
    assign mc_dfi_lp_data_ack      = phy_dfi_lp_data_ack;

endmodule

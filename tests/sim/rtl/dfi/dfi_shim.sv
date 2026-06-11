// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2024-2026 sean galloway
//
// DFI v2.1 wire shim — passthrough between an MC-side BFM and a PHY-side
// BFM. The shim has no logic; it lets us attach two monitors (one on each
// side) and verify they see the same packets, exercising the real cocotb
// signal-binding path without a behavioral loopback.
//
// MVP envelope: DFI v2.1 + DDR1/2/3/LPDDR1/2. 15 signals across the
// command, write_data, and read_data sub-interfaces. The PHY-facing
// rddata path (rddata, rddata_valid) is the only direction where the
// PHY-side BFM drives — everything else is MC-driven.

module dfi_shim #(
    parameter int ADDR_WIDTH     = 16,
    parameter int BANK_WIDTH     = 3,
    parameter int CS_WIDTH       = 1,
    parameter int CTRL_WIDTH     = 1,
    parameter int DATA_WIDTH     = 64,
    parameter int DATA_EN_WIDTH  = 1,
    parameter int DATA_MASK_BITS = 8,    // data_width / 8
    parameter int RD_VALID_WIDTH = 1,
    parameter int ERROR_INFO_WIDTH = 8,   // v3.0+ error sub-interface code width
    parameter int TRAINING_PHASE_WIDTH = 3 // 0..4 covers our v3.0 phase enum
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
    // Error sub-interface (PHY drives; v3.0+ only — wires always present
    // for shim simplicity, ignored by v2.1 tests)
    output logic [CTRL_WIDTH-1:0]     mc_dfi_error,
    output logic [ERROR_INFO_WIDTH-1:0] mc_dfi_error_info,
    // CRC alert (PHY drives; v3.0+, DDR4-specific)
    output logic [CTRL_WIDTH-1:0]     mc_dfi_crc_alert,
    // Update interface — MC-initiated (MC drives req, PHY acks)
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_ctrlupd_req,
    output logic [CTRL_WIDTH-1:0]     mc_dfi_ctrlupd_ack,
    // Update interface — PHY-initiated (PHY drives req, MC acks; v3.0+)
    output logic [CTRL_WIDTH-1:0]     mc_dfi_phyupd_req,
    input  logic [CTRL_WIDTH-1:0]     mc_dfi_phyupd_ack,
    // Training interface (PHY drives; v3.0+)
    output logic [CTRL_WIDTH-1:0]           mc_dfi_training_active,
    output logic [TRAINING_PHASE_WIDTH-1:0] mc_dfi_training_phase,

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
    // CRC alert (PHY drives; v3.0+, DDR4-specific)
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_crc_alert,
    // Update interface — MC-initiated mirror
    output logic [CTRL_WIDTH-1:0]     phy_dfi_ctrlupd_req,
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_ctrlupd_ack,
    // Update interface — PHY-initiated mirror (v3.0+)
    input  logic [CTRL_WIDTH-1:0]     phy_dfi_phyupd_req,
    output logic [CTRL_WIDTH-1:0]     phy_dfi_phyupd_ack,
    // Training interface mirror (PHY drives)
    input  logic [CTRL_WIDTH-1:0]           phy_dfi_training_active,
    input  logic [TRAINING_PHASE_WIDTH-1:0] phy_dfi_training_phase
);

    // ----- MC → PHY (command + write-data + rddata_en) -----
    assign phy_dfi_address     = mc_dfi_address;
    assign phy_dfi_bank        = mc_dfi_bank;
    assign phy_dfi_cas_n       = mc_dfi_cas_n;
    assign phy_dfi_ras_n       = mc_dfi_ras_n;
    assign phy_dfi_we_n        = mc_dfi_we_n;
    assign phy_dfi_cs_n        = mc_dfi_cs_n;
    assign phy_dfi_cke         = mc_dfi_cke;
    assign phy_dfi_odt         = mc_dfi_odt;
    assign phy_dfi_reset_n     = mc_dfi_reset_n;
    assign phy_dfi_wrdata      = mc_dfi_wrdata;
    assign phy_dfi_wrdata_en   = mc_dfi_wrdata_en;
    assign phy_dfi_wrdata_mask = mc_dfi_wrdata_mask;
    assign phy_dfi_rddata_en   = mc_dfi_rddata_en;

    // ----- PHY → MC (read data + error + CRC alert + ack/req updates) -----
    assign mc_dfi_rddata       = phy_dfi_rddata;
    assign mc_dfi_rddata_valid = phy_dfi_rddata_valid;
    assign mc_dfi_error        = phy_dfi_error;
    assign mc_dfi_error_info   = phy_dfi_error_info;
    assign mc_dfi_crc_alert    = phy_dfi_crc_alert;
    assign mc_dfi_ctrlupd_ack  = phy_dfi_ctrlupd_ack;
    assign mc_dfi_phyupd_req   = phy_dfi_phyupd_req;
    assign mc_dfi_training_active = phy_dfi_training_active;
    assign mc_dfi_training_phase  = phy_dfi_training_phase;

    // ----- MC → PHY (also update mirror) -----
    assign phy_dfi_ctrlupd_req = mc_dfi_ctrlupd_req;
    assign phy_dfi_phyupd_ack  = mc_dfi_phyupd_ack;

endmodule

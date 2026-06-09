# Include directories
+incdir+$REPO_ROOT/rtl/amba/includes

# Bridge RTL files (generated)
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/bridge_a_axi4_widthmix_4x4_pkg.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/cpu_adapter.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/dma_adapter.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/gpu_adapter.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/vpu_adapter.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/bridge_a_axi4_widthmix_4x4.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/bridge_a_axi4_widthmix_4x4_xbar.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/ddr0_adapter.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/ddr1_adapter.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/scratch_adapter.sv
tests/sim/rtl/bridges/bridge_a_axi4_widthmix_4x4/sram_adapter.sv

# AXI4 Wrapper modules (timing isolation)
# Master adapters use axi4_slave_* (act as AXI slave to external master)
$REPO_ROOT/rtl/amba/axi4/axi4_slave_wr.sv
$REPO_ROOT/rtl/amba/axi4/axi4_slave_rd.sv
# Slave adapters use axi4_master_* (act as AXI master to external slave)
$REPO_ROOT/rtl/amba/axi4/axi4_master_wr.sv
$REPO_ROOT/rtl/amba/axi4/axi4_master_rd.sv

# GAXI skid buffers (used by wrappers and converters)
$REPO_ROOT/rtl/amba/gaxi/gaxi_skid_buffer.sv

# Width converters (for data width adaptation).
# axi_data_{upsize,dnsize} are validated primitives used by the
# axi4_dwidth_converter_{rd,wr} wrappers for the W/R data path.
$REPO_ROOT/projects/components/converters/rtl/axi_data_upsize.sv
$REPO_ROOT/projects/components/converters/rtl/axi_data_dnsize.sv
$REPO_ROOT/projects/components/converters/rtl/axi4_dwidth_converter_rd.sv
$REPO_ROOT/projects/components/converters/rtl/axi4_dwidth_converter_wr.sv
$REPO_ROOT/projects/components/converters/rtl/axil_to_axi4_wide_align_wr.sv
$REPO_ROOT/projects/components/converters/rtl/axil_to_axi4_wide_align_rd.sv
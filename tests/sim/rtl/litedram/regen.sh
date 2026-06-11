#!/bin/bash
# Regenerate LiteDRAM standalone Verilog for the DFI BFM co-sim.
#
# Output: tests/sim/rtl/litedram/ddr3/gateware/litedram_core.v
#
# Requirements (install once into the project venv):
#   pip install litedram litex migen pyyaml \
#               liteeth liteiclink litescope litesata litesdcard \
#               git+https://github.com/litex-hub/pythondata-misc-tapcfg.git
#
# Python 3.12 prerequisite:
#   The Migen bytecode tracer has a Python 3.12 incompatibility (it
#   doesn't know about the new CALL opcode or inline CACHE entries).
#   Apply the patch in `migen_py312_tracer.patch` once after install
#   (or after re-creating the venv):
#     cd $(python3 -c "import migen, os; print(os.path.dirname(migen.__file__))")
#     patch -p1 < $REPO/tests/sim/rtl/litedram/migen_py312_tracer.patch
#
# Generated Verilog is NOT committed (huge); rerun this script when
# the YAML config or LiteDRAM upstream changes.

set -euo pipefail

THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${THIS_DIR}/../../../.." && pwd)"
YAML="${THIS_DIR}/arty_ddr3_nocpu.yml"
OUT_DIR="${THIS_DIR}/ddr3"

# Make sure the env_python activation has run; the script's caller
# is responsible for: source env_python.

# Remove old gen artifacts to ensure a clean run
rm -rf "${OUT_DIR}"

litedram_gen \
    --sim \
    --no-compile \
    --output-dir "${OUT_DIR}" \
    "${YAML}"

echo
echo "Generated: ${OUT_DIR}/gateware/litedram_core.v"
wc -l "${OUT_DIR}/gateware/litedram_core.v"

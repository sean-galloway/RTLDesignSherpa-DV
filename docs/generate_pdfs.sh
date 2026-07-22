#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# CocoTB Framework — PDF book generator (one book per BFM family)
# ------------------------------------------------------------
# Adapted from RTLDesignSherpa/docs/markdown/generate_rtl_pdfs.sh. Ground truth
# for the pipeline mechanics is RTLDesignSherpa/bin/DOC_GENERATION.md.
#
# For each book this script:
#   1. auto-generates a link-only index (the page set + order); with
#      --skip-index-content only the LINKS matter -- the PDF TOC is built from
#      the page headings, so the index carries no prose.
#   2. renders DOCX + PDF via bin/md_to_docx.py, inlining every linked page in
#      order (--expand-index), starting each page on a new page (--pagebreak).
#      md_to_docx renders ```mermaid fences to PNG via mmdc at build time.
#
# Output filenames are STABLE (no version); the revision shows on the title
# page. Usage: ./generate_pdfs.sh [--rev X.Y] [book ...]   (default: all)
# ------------------------------------------------------------

REV="0.5.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"        # docs/
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel)"
MD2DOCX="${REPO_ROOT}/bin/md_to_docx.py"
STYLE_TMPL="${SCRIPT_DIR}/dv_pdf_styles.yaml"
COMP="${SCRIPT_DIR}/components"
OUTDIR="${SCRIPT_DIR}/pdf"                                        # docs/pdf/*.pdf
mkdir -p "${OUTDIR}"

ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--rev) REV="${2:?}"; shift 2;;
    -h|--help) echo "Usage: $0 [--rev X.Y] [book ...]"; exit 0;;
    *) ARGS+=("$1"); shift;;
  esac
done

# gen_index <index_path> <title> <file...>  — emit a link-only index
gen_index() {
  local out="$1" title="$2"; shift 2
  local dir; dir="$(dirname "$out")"
  { echo "# ${title}"; echo;
    echo "<!-- Auto-generated link index for PDF build. Regenerate via generate_pdfs.sh -->";
    echo; } > "$out"
  local f rel h1
  for f in "$@"; do
    rel="$(realpath --relative-to="$dir" "$f")"
    h1="$(grep -m1 '^# ' "$f" 2>/dev/null | sed 's/^#\s*//')"
    [[ -z "$h1" ]] && h1="$(basename "$f" .md)"
    echo "- [${h1}](${rel})" >> "$out"
  done
}

# build_book <title> <subtitle> <index_path> <out_name> [lot lof low]
build_book() {
  local title="$1" subtitle="$2" index="$3" name="$4"; shift 4
  local lot=false lof=false low=false a
  for a in "$@"; do case "$a" in lot) lot=true;; lof) lof=true;; low) low=true;; esac; done
  local outbase="${OUTDIR}/${name}"
  local tmpstyle="${SCRIPT_DIR}/.book_styles.yaml"
  sed -e "s|__TITLE__|${title}|" -e "s|__SUBTITLE__|${subtitle}|" \
      -e "s|__LOT__|${lot}|" -e "s|__LOF__|${lof}|" -e "s|__LOW__|${low}|" \
      "${STYLE_TMPL}" > "${tmpstyle}"
  echo "------------------------------------------------------------"
  echo " Building: ${title}  ->  docs/pdf/${name}.pdf"
  echo "------------------------------------------------------------"
  python3 "${MD2DOCX}" "${index}" "${outbase}.docx" \
    --style "${tmpstyle}" \
    --expand-index --skip-index-content --strip-doc-header \
    --toc --number-sections --pdf --pagebreak --narrow-margins \
    --quiet
  rm -f "${tmpstyle}" "${outbase}.docx"          # keep only the PDF
}

want() { [[ ${#ARGS[@]} -eq 0 ]] || printf '%s\n' "${ARGS[@]}" | grep -qx "$1"; }

SUB="CocoTB Verification Framework — Rev ${REV}"

# one book per component family. LC_ALL=C byte-order sort keeps overview/index
# ordering stable and puts *_overview ahead of per-module pages.
family_book() {  # <key> <Title> <out-name> <doc-subdir>
  local key="$1" title="$2" out="$3" sub="$4"
  want "$key" || return 0
  local files=()
  mapfile -t files < <(LC_ALL=C ls "${COMP}/${sub}"/*.md 2>/dev/null | grep -vE '/_book_')
  [[ ${#files[@]} -eq 0 ]] && { echo "  (no docs for ${key}, skip)"; return 0; }
  gen_index "${COMP}/${sub}/_book_${key}_index.md" "${title}" "${files[@]}"
  build_book "${title}" "${SUB}" "${COMP}/${sub}/_book_${key}_index.md" "${out}" lot
  rm -f "${COMP}/${sub}/_book_${key}_index.md"
}

family_book apb      "APB4 BFM"            CocoTB_APB4        apb
family_book apb5     "APB5 BFM"            CocoTB_APB5        apb5
family_book axi4     "AXI4 BFM"            CocoTB_AXI4        axi4
family_book axi5     "AXI5 BFM"            CocoTB_AXI5        axi5
family_book axil4    "AXI4-Lite BFM"       CocoTB_AXI4_Lite   axil4
family_book axis4    "AXI4-Stream BFM"     CocoTB_AXI4_Stream axis4
family_book axis5    "AXI5-Stream BFM"     CocoTB_AXI5_Stream axis5
family_book dfi      "DFI BFM"             CocoTB_DFI         dfi
family_book fifo     "FIFO BFM"            CocoTB_FIFO        fifo
family_book gaxi     "GAXI BFM"            CocoTB_GAXI        gaxi
family_book smbus    "SMBus BFM"           CocoTB_SMBus       smbus
family_book uart     "UART BFM"            CocoTB_UART        uart
family_book wavedrom "WaveDrom Capture"    CocoTB_WaveDrom    wavedrom
family_book shared   "Shared Infrastructure" CocoTB_Shared    shared

# Scoreboards live outside components/
if want scoreboards; then
  files=()
  mapfile -t files < <(LC_ALL=C ls "${SCRIPT_DIR}/scoreboards"/*.md 2>/dev/null | grep -vE '/_book_')
  if [[ ${#files[@]} -gt 0 ]]; then
    gen_index "${SCRIPT_DIR}/scoreboards/_book_scoreboards_index.md" "Scoreboards" "${files[@]}"
    build_book "Scoreboards" "${SUB}" "${SCRIPT_DIR}/scoreboards/_book_scoreboards_index.md" CocoTB_Scoreboards lot
    rm -f "${SCRIPT_DIR}/scoreboards/_book_scoreboards_index.md"
  fi
fi

echo
echo "Books generated (rev ${REV}) in docs/pdf/"

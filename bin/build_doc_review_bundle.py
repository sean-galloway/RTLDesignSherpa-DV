#!/usr/bin/env python3
"""
Rebuild the documentation review bundles from the CURRENT docs and package source.

Each component family (and each part of an oversized family) becomes a
self-contained review unit: DOCS.md (the documentation) + SOURCE.py (the Python
the pages document, concatenated).

This is the DV-repo sibling of RTLDesignSherpa's bin/build_review_bundle.py. The
difference that matters: ground truth here is the Python BFM source, not RTL.
There is no dependency closure to compute -- a component family's package
directory IS the unit -- so the matching is by directory rather than by module
name.

PROCESS RULE (inherited, and it was learned the hard way): clear the staging
area, package EVERYTHING, then send only the packages that are needed. Never
package a subset, and never hand-patch a bundle.

A stale or partial bundle produces findings indistinguishable from real ones:
the reviewer reports defects that were already fixed, and you cannot tell from
the output which is which. Rebuilding everything is cheap; re-reviewing stale
content is not.

Usage: python3 bin/build_doc_review_bundle.py [out_dir]
"""
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else '/mnt/data/github/dv-doc-review'
DOCS = 'docs'
SRC = 'src/CocoTBFramework'
LIMIT = 120_000 * 4          # chars; ~120k tokens per unit

os.chdir(REPO)

# ---- component families: docs/components/<key>/ <-> src/.../components/<key>/ ----
# Plus two special units: the scoreboards, and the top-level/overview pages.
TITLES = {
    'apb': 'APB4 BFM', 'apb5': 'APB5 BFM',
    'axi4': 'AXI4 BFM', 'axi5': 'AXI5 BFM', 'axil4': 'AXI4-Lite BFM',
    'axis4': 'AXI4-Stream BFM', 'axis5': 'AXI5-Stream BFM',
    'dfi': 'DFI BFM', 'fifo': 'FIFO BFM', 'gaxi': 'GAXI BFM (shared workhorse layer)',
    'shared': 'Shared infrastructure', 'smbus': 'SMBus BFM', 'uart': 'UART BFM',
    'wavedrom': 'WaveDrom waveform capture', 'misc': 'Arbiter monitors and misc',
}
# docs/components/misc/ documents code that lives in components/shared/.
SRC_OVERRIDE = {'misc': 'shared'}


def read(p):
    return open(p, encoding='utf-8', errors='replace').read()


def write_unit(d, title, docs, srcs, note=''):
    os.makedirs(d, exist_ok=True)
    with open(f'{d}/DOCS.md', 'w', encoding='utf-8') as fh:
        fh.write(f'# {title}\n\n{len(docs)} documentation files.{note}\n'
                 'Each section is one source file; cite findings by the path in its banner.\n\n---\n')
        for p in docs:
            fh.write('\n\n<!-- ================================================= -->\n'
                     f'<!-- SOURCE FILE: {p} -->\n'
                     '<!-- ================================================= -->\n\n')
            fh.write(read(p))
    with open(f'{d}/SOURCE.py', 'w', encoding='utf-8') as fh:
        fh.write(f'# {title} -- Python source for the documents in DOCS.md\n'
                 f'# {len(srcs)} modules.\n'
                 '# GROUND TRUTH: if a doc disagrees with this, the doc is wrong.\n')
        for p in srcs:
            fh.write('\n\n# =================================================\n'
                     f'# SOURCE FILE: {p}\n'
                     '# =================================================\n\n')
            fh.write(read(p))
    return os.path.getsize(f'{d}/DOCS.md') + os.path.getsize(f'{d}/SOURCE.py')


def modules_for(doc_path, srcs):
    """The module(s) a doc page documents, matched by filename stem.

    Doc pages are named components_<family>_<module>.md, so the module stem is
    the tail of the doc stem. Index/overview pages match nothing and get the
    whole family's source instead (see split handling below).
    """
    stem = os.path.basename(doc_path)[:-3]
    hits = [p for p in srcs
            if stem.endswith(os.path.basename(p)[:-3]) and os.path.basename(p) != '__init__.py']
    # Longest match wins: packet_factory must not also match packet.
    if hits:
        best = max(len(os.path.basename(p)) for p in hits)
        return [p for p in hits if len(os.path.basename(p)) == best]
    return []


def units():
    """Yield (key, title, docs, srcs) for every review unit."""
    for key in sorted(TITLES):
        doc_dir = f'{DOCS}/components/{key}'
        if not os.path.isdir(doc_dir):
            continue
        docs = sorted(glob.glob(f'{doc_dir}/**/*.md', recursive=True))
        src_dir = f'{SRC}/components/{SRC_OVERRIDE.get(key, key)}'
        srcs = sorted(p for p in glob.glob(f'{src_dir}/**/*.py', recursive=True)
                      if '__pycache__' not in p)
        if docs:
            yield key, TITLES[key], docs, srcs

    sb_docs = sorted(glob.glob(f'{DOCS}/scoreboards/**/*.md', recursive=True))
    sb_srcs = sorted(p for p in glob.glob(f'{SRC}/scoreboards/**/*.py', recursive=True)
                     if '__pycache__' not in p)
    if sb_docs:
        yield 'scoreboards', 'Scoreboards', sb_docs, sb_srcs

    # Top-level pages: everything under docs/ not already covered above.
    covered = {p for _, _, d, _ in
               [(k, t, d, s) for k, t, d, s in units_cache] for p in d} if units_cache else set()
    top = sorted(p for p in glob.glob(f'{DOCS}/**/*.md', recursive=True) if p not in covered)
    if top:
        yield 'overview', 'Top-level and overview pages', top, []


units_cache = []
units_cache = [u for u in units() if u[0] != 'overview']
all_units = units_cache + [u for u in units() if u[0] == 'overview']

os.system(f'rm -rf {OUT}/books')
manifest = []
for key, title, docs, srcs in all_units:
    total = sum(os.path.getsize(p) for p in docs) + sum(os.path.getsize(p) for p in srcs)
    if total <= LIMIT:
        sz = write_unit(f'{OUT}/books/{key}', title, docs, srcs)
        manifest.append((key, 1, sz // 4))
        print(f'  {key:12s} 1 unit   ~{sz//4000}k tok  ({len(docs)} docs, {len(srcs)} modules)')
    else:
        # Split by docs, pairing each part with ONLY the modules its own pages
        # document. Carrying the whole family source into every part multiplies
        # the bundle (shared/ went to 12 parts / 1.4M tokens that way) without
        # adding ground truth the part's reviewer can use. Pages that match no
        # module (index, overview) carry the unmatched remainder so nothing is
        # silently dropped.
        matched = {p: modules_for(p, srcs) for p in docs}
        orphans = [p for p in srcs if not any(p in m for m in matched.values())]
        parts, cur, cursz = [], [], 0
        for p in docs:
            s = os.path.getsize(p) + sum(os.path.getsize(m) for m in matched[p])
            if cur and cursz + s > LIMIT:
                parts.append(cur)
                cur, cursz = [], 0
            cur.append(p)
            cursz += s
        if cur:
            parts.append(cur)
        tot = 0
        for i, part in enumerate(parts, 1):
            psrc = [m for p in part for m in matched[p]]
            if i == 1:
                psrc = orphans + psrc      # unmatched modules ride with part 1
            seen = set()
            psrc = [m for m in psrc if not (m in seen or seen.add(m))]
            tot += write_unit(f'{OUT}/books/{key}/parts/part_{i:02d}', title, part, psrc,
                              note=f' Part {i} of {len(parts)}.')
        manifest.append((key, len(parts), tot // 4))
        label = '1 unit  ' if len(parts) == 1 else f'{len(parts)} parts '
        print(f'  {key:12s} {label} ~{tot//4000}k tok  '
              f'({len(docs)} docs, {len(srcs)} modules)')

json.dump([{'book': k, 'parts': n, 'ktok': t // 1000} for k, n, t in manifest],
          open(f'{OUT}/.manifest.json', 'w'), indent=1)
print(f'\n  bundle rebuilt at {OUT} from current working tree')

# Documentation humanization pass — structural preamble

This brief wraps the style guide that follows it. The guide governs **voice**.
This preamble governs **structure**, and it wins wherever the two seem to
conflict.

You are rewriting the documentation of an open-source Python verification
framework (`cocotb-framework` on PyPI: cocotb BFMs, scoreboards and shared
infrastructure for AMBA protocols, DFI, UART, SMBus) before it is publicly
announced.

**The job is to rewrite prose, not to review and not to restructure.** This
documentation was largely generated and reads like it. It has just been audited
against the source and corrected, so it is accurate — it is simply flat,
repetitive, and full of the tells that make a reader assume nobody cared. Make
it sound like the engineer who built it wrote it.

## Structural preservation — the hard rule

These documents are build inputs, not just pages. Markup that looks decorative
is load-bearing: navigation, cross-page indexes and rendered diagrams are
generated from it. Prose that reads beautifully while silently emptying a
generated list or breaking a link is a worse outcome than prose you did not
touch.

Change prose. Do not touch any of the following:

- **Heading hierarchy** — levels and order. Tables of contents are generated
  from it, and heading *depth* is semantic (a `###` and a `####` are not
  interchangeable). You may reword a heading's text; you may not change its
  level, split it, merge it, or reorder sections.
- **Caption lines.** A line beginning `: ` immediately after a table is a
  Pandoc caption and is what populates the List of Tables. Headings of the form
  `Figure N: …` and `Waveform N: …` populate the Lists of Figures and
  Waveforms. These encode list membership; they are not stray text. Leave the
  form intact — reword the caption text only.
- **Fenced code blocks and their language tags** — including ```mermaid
  blocks, which render to diagrams. Never edit inside a fence.
- **Tables** — including pipe alignment. Reword cell text if it is prose;
  never restructure columns or rows.
- **Links and asset paths** — inter-page `.md` links and image/diagram paths.
  Index pages are walked recursively to assemble books and site navigation, so
  a dropped or reworded link target silently removes a page.
- **Inline identifiers** — signal, module, class, method and parameter names,
  file paths, and `file:line` references. If a name reads awkwardly, that is
  the code's problem, not yours.
- **No emojis.** Hard rule: they break the LaTeX/PDF path. Do not introduce
  any, in headings, prose or tables.

If a section is so badly structured that fixing the prose is not enough, say so
in the Problems section rather than restructuring it yourself.

## What you have

Each unit is one component family's documentation: every page concatenated,
each preceded by an HTML comment giving its real source path.

This round is **documentation only — no source code is provided, deliberately.**
The accuracy rounds already happened against the source; this pass changes prose
only. Do not propose content corrections you cannot support from the documents
themselves.

## What to return

For each page, return the rewritten page in full, keyed by the source path from
its banner comment so it can be dropped straight back into the repo. Preserve
the banner comments.

## Problems — the exception, not the task

Do **not** produce a findings list. Do not hunt for defects.

If while rewriting you hit something genuinely bad — two pages that contradict
each other, a code example that obviously cannot run, a number that is
self-inconsistent — put it in a short `## Problems` section at the end, with the
source path and one sentence each.

The bar is: **would a reader act on this and get burned?** If yes, flag it.
Awkward phrasing, a missing example, or a section you would have organized
differently is not a problem — that is just something for you to fix while
rewriting. Err toward silence. A handful of real ones is worth more than a long
list nobody will read.

## Notes on this codebase

- `GAXI` is the shared "generic AXI" workhorse layer. The AXI4/AXI5/AXI-Lite/
  AXI-Stream/FIFO BFMs are all built on it. Documentation that treats it as
  just another protocol is missing the point — it is the substrate.
- `DFI` is the newest component and under active development. Its docs are thin.
  Rewriting them in voice is welcome; inventing capability claims is not.
- Many pages are auto-generated in origin and share boilerplate almost verbatim
  across families. Do not preserve that symmetry for its own sake — identical
  prose repeated a dozen times is precisely what makes this read as
  machine-written. Say what is true about *this* component.

---

The style guide begins below. Follow it closely for voice; the structural rules
above override it wherever they touch.

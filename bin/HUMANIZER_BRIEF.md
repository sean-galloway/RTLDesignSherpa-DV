# CocoTBFramework docs — humanization pass

You are rewriting the documentation of an open-source Python verification
framework (`cocotb-framework` on PyPI: cocotb BFMs, scoreboards and shared
infrastructure for AMBA protocols, DFI, UART, SMBus) before it is publicly
announced.

**The job is to rewrite, not to review.** Most of this documentation was
generated and reads like it. It is technically accurate — it was just audited
against the source and corrected — but it is flat, repetitive, and full of the
tells that make a reader assume nobody actually cared. Your task is to make it
sound like it was written by the engineer who built the thing.

Write in the voice defined in `STYLE_GUIDE.md`, which accompanies this brief.
Follow it closely; it is the point of the exercise.

## What you have

Each directory under `books/` is one self-contained unit:

- `DOCS.md` — every documentation page for one component family, concatenated.
  Each page is preceded by an HTML comment giving its real source path.
- `SOURCE.py` — the Python those pages document, concatenated the same way.
  **This is ground truth.** Where a document and the source disagree, the
  document is wrong.

## What to return

For each page in `DOCS.md`, return the rewritten page, keyed by the source path
from its banner comment so it can be dropped back into the repo. Keep the
Markdown structure usable: headings, code fences, tables and links must survive.

Preserve exactly, without rewording:
- Code examples, signatures, parameter names, class and method names
- Numbers: widths, depths, latencies, bit ranges, timing values
- Import paths and file paths
- Anything inside a code fence

Rewrite freely: prose, headings, transitions, explanations, ordering within a
section, and the framing of *why* something exists.

## Critique — the exception, not the task

Do **not** produce a findings list. Do not hunt for defects. The documentation
was just audited and the errors were fixed; a second critique pass is not what
this is for.

But if while rewriting you hit something genuinely bad — a documented feature
that does not exist in `SOURCE.py`, a number that is flatly wrong, a code
example that cannot run, two pages that contradict each other — say so. Put it
in a short `## Problems` section at the end of your response, with the source
path and one sentence each.

Bar for inclusion: **would a reader act on this and get burned?** If yes, flag
it. Awkward phrasing, a missing example, or a section you would have organized
differently is not a problem — that is just something for you to fix while
rewriting. Err toward silence. A handful of real ones is worth more than a long
list of nitpicks nobody will read.

## Notes on this codebase

- `GAXI` is the shared "generic AXI" workhorse layer. The AXI4/AXI5/AXI-Lite/
  AXI-Stream/FIFO BFMs are built on it. Documentation that treats it as just
  another protocol is missing the point — it is the substrate.
- `DFI` is the newest component and is under active development. Its docs are
  thin compared to the rest. Rewriting them in voice is welcome; inventing
  capability claims is not.
- Several pages are auto-generated in origin and share boilerplate almost
  verbatim across families. Do not preserve that symmetry for its own sake —
  identical prose repeated eleven times is one of the things that makes this
  read as machine-written. Say the thing that is true about *this* component.

---
title: Differential testing against an anchor
summary: When two implementations encode the same truth table, name one the anchor and test the other against it bit-for-bit. Golden vectors are hand-derived from the spec - and when they disagree with the code, the vector is often the one that is wrong.
---

# Differential testing against an anchor

A generic engine and a hand-written codec can encode the same JEDEC truth
table. That duplication is fine — often it is the point, because the generic
one is what integration consumes and the hand-written one is what a reviewer
can check against the spec. What is *not* fine is two implementations with
equal authority, because then a disagreement has no resolution.

**Name one the anchor.** The anchor is the closest thing to a literal
transcription of the specification. Everything else is tested against it,
bit-for-bit, over the full field ranges.

## The shape

```python
@pytest.mark.parametrize("pc,sid,ba,row", [...])
def test_act_matches_handwritten(pc, sid, ba, row):
    assert ROW.encode("act", pc=pc, sid=sid, ba=ba, row=row) == \
        hc.encode_row_act(pc=pc, sid=sid, ba=ba, row=row)
```

Worked examples in this repo:

- `HBM4_ROW_CA_MAP` / `HBM4_COL_CA_MAP` are differentially tested against
  `hbm4_commands.py`, which transcribes JESD270-4A Tables 33/34.
- `lpddr_ca.py` (LPDDR2, JESD209-2F Table 60) is an anchor with a second
  consumer: the RTL command formatter in the main repo encodes against the
  same transcription, and a conformance test decodes the RTL's output with
  it. Any map that duplicates it must be tested against it, not replace it
  — see `vault/Tasks/dfi/open.md` DFI-009.

## Golden vectors are hand-derived, and you will get some wrong

A golden vector transcribed by hand from a truth table is only as good as the
transcription. Two real cases from the DFI CA work:

- An LPDDR5 ACT-1 expectation omitted the command's own opcode bits, so the
  test demanded `0b1111000` where the encoder correctly produced
  `0b1111111`. **The code was right and the test was wrong.**
- A DDR5 WRP expectation had the wrong constant for the same reason.

This is the failure direction you want, and it is an argument for hand-deriving
vectors rather than capturing them from the implementation. A vector captured
from the code under test asserts only that the code has not changed; a vector
derived from the spec asserts that the code is *correct*. When they disagree,
re-read the table before touching the implementation.

## Keep the tables from drifting apart

When a name exists in two places — a map and a translation table, an encoder
and a decoder — add a test that walks one and asserts against the other:

```python
def test_translations_name_real_commands(camap):
    known = {c.name for c in camap.commands}
    for name, tr in TRANSLATIONS[camap.name].items():
        assert name in known, f"{camap.name}: {name} not in map"
```

That is what stops a renamed command from silently orphaning its translation,
which no functional test would notice.

See [[spec-fidelity]] for where the anchor's authority comes from.

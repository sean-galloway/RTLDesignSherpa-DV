# DFI Semantic-Shift Catalog (draft)

> **Status:** design pressure-test, not user-facing docs. Iterate freely here
> before any code is written. If a shift area doesn't fit the architecture
> below, the architecture is what we change — not the area.
>
> **Scope:** DFI v2.1 through v5.x, covering DDR1-5 and LPDDR1-5. v6.0 dropped
> every DDR/LPDDR type below DDR5/LPDDR5 and added LPDDR6 and HBM4 — that's
> a big enough break to be a future BFM generation, not an extension of this
> one. The v6.0 research is preserved in the `project_dfi_v6_scope_changes`
> memory note; this BFM stops at v5.x.

## Why this exists

Most DFI signals are **additive** across revisions — a new version adds a wire,
and the old wires keep their old meaning. Those are easy: the signal envelope
(`dfi_signals.py`) gates them with `min_version` / `max_version` and the BFM
needs zero version-dispatched logic.

A small set of behaviors **change meaning** between revisions. You can't hide
those behind "does the signal exist?" checks, because the same wire is sitting
right there with a different contract on it. The list:

- The CRC handshake (introduced v3.0, mode bits added later, Link vs DRAM CRC split)
- The update interface (rewritten v3.0, self-refresh exit added v4.0)
- The PHY-master/PHY-managed interface (new v4.0, renamed v5.2)
- The disconnect protocol (new v4.0)
- The frequency-change handshake (Acknowledged vs Not-Acknowledged protocols)
- Training (v3.0 introduced it, v3.1 added PHY-Requested mode, v4.0 made it optional)
- The error interface (new v3.0)
- CA-parity error signaling (new v3.0 for DDR4)

Left unchecked, these turn into scattered `if version >= X:` checks that
quietly rot as new revisions land. This doc enumerates the shifts, sketches
the shape of each handler, and pressure-tests the claim that one architecture
covers all of them.

## The architecture

Two concrete pieces:

```python
# 1. Per-version behavior classes — one method per shift area, inheritance
#    handles "v5 is mostly v4".
class DFIv2_1Behavior:
    def crc(self, bus, state): ...                # raises NotImplementedError pre-v3.0
    def update_request(self, bus, state): ...
    def phy_master(self, bus, state): ...
    # ...

class DFIv3_0Behavior(DFIv2_1Behavior):
    def crc(self, bus, state): ...                # CRC introduced
    def update_request(self, bus, state): ...     # update i/f rewritten

class DFIv4_0Behavior(DFIv3_0Behavior):
    def phy_master(self, bus, state): ...         # PHY master added
    def disconnect(self, bus, state): ...         # disconnect protocol added

class DFIv5_2Behavior(DFIv4_0Behavior):
    def phy_master(self, bus, state): ...         # renamed; semantics evolved
    # everything else inherited

# 2. Registry dict — the ONLY place that knows about versions.
VERSION_BEHAVIOR = {
    DFIVersion.V2_1: DFIv2_1Behavior,
    DFIVersion.V3_0: DFIv3_0Behavior,
    DFIVersion.V3_1: DFIv3_0Behavior,   # v3.1 is v3.0 + LPDDR3 (additive)
    DFIVersion.V4_0: DFIv4_0Behavior,
    DFIVersion.V5_0: DFIv4_0Behavior,   # v5.0 is corrections-only
    DFIVersion.V5_1: DFIv4_0Behavior,   # v5.1 is new signals (additive)
    DFIVersion.V5_2: DFIv5_2Behavior,   # PHY-master renamed
    # v6.0+ is a future BFM generation — see scope statement at the top.
}
```

Inside the BFM:

```python
behavior_cls = VERSION_BEHAVIOR[self.dfi_version]
self.behavior = behavior_cls()

# At every shift point in the BFM:
self.behavior.crc(self.bus, self.state)
self.behavior.update_request(self.bus, self.state)
# No `if version ==` anywhere.
```

Add a new revision → one row in the registry. Add a new shift area → one
method on the base class. Override v5 behavior for one area → one method in
`DFIv5_xBehavior`. Everything else falls out of the inheritance.

## How to read each section below

For each shift area:

- **What it is** — one sentence.
- **Versions** — when introduced, when changed.
- **Spec references** — section numbers in the relevant PDF (anchored on v5.2
  unless noted, since it's the densest reference).
- **What shifts** — the actual contract difference between revisions.
- **Method shape** — proposed signature on the behavior class.
- **Inheritance plan** — which subclass owns which override.
- **Open questions** — what to nail down before coding this area.

## Shift areas

### 1. CRC error handshake

**What it is:** cyclic redundancy check on write data (DRAM-side and Link-side),
plus the error-reporting handshake when a mismatch is detected.

**Versions:** introduced in v3.0 (DDR4). v4.0+ added PHY CRC support
(`phycrc_mode=1`) alongside MC CRC support (`phycrc_mode=0`). v5.x added
"Link DQ CRC" as a separate sub-interface (§3.14).

**Spec references (v5.2):**
- §3.2.3 (Write Data CRC: DRAM CRC vs Link CRC)
- §4.7.5 (Cyclic Redundancy Check — Write)
- §4.12 (CA Parity Signaling and CA Parity, CRC Errors)

**What shifts:**
- *Pre-v3.0:* no CRC concept. Behavior raises `NotImplementedError`.
- *v3.0:* CRC introduced. MC-driven; PHY reports errors via the error interface.
- *v4.0:* `phycrc_mode` parameter added. The PHY can also drive CRC for some
  configurations.
- *v5.x:* Link DQ CRC sub-interface added — separate from DRAM CRC. Two
  independent CRC paths can be live at once.

**Method shape:**
```python
def crc(self, bus, state) -> CRCEvent | None:
    """Sample CRC-related signals this cycle; return an event if a
    CRC error was reported, else None."""
```

**Inheritance plan:**
- `DFIv2_1Behavior.crc()` → returns `None` always (CRC doesn't exist yet).
- `DFIv3_0Behavior.crc()` → MC-CRC path only.
- `DFIv4_0Behavior.crc()` → adds `phycrc_mode` branching.
- `DFIv5_xBehavior.crc()` → adds the Link DQ CRC path.

**Open questions:**
- Is `CRCEvent` one dataclass with optional fields, or one type per CRC variant
  (DRAMCRCEvent / LinkCRCEvent / CAParityEvent)? I'm leaning toward one
  dataclass with a `kind` enum so the caller can pattern-match.
- Does CRC need its own `state` field on the BFM, or does it piggyback on the
  existing per-bank state? Probably its own — CRC is per-channel, not per-bank.

---

### 2. Update interface

**What it is:** PHY-initiated and MC-initiated requests to pause traffic for
PHY recalibration or training touch-up.

**Versions:** existed pre-v3.0 in a simpler form. v3.0 "enhanced the update
interface". v4.0 added self-refresh-exit semantics. (v6.0 expanded it
substantially — out of scope for this generation.)

**Spec references (v5.2):**
- §3.4 (Update Interface)
- §4.9 (Update: MC-initiated, PHY-initiated, DFI Bus Idle)
- §4.16 (DFI Disconnect Protocol §4.16.1 references update interface
  interactions)

**What shifts:**
- *v2.1:* simple MC-initiated request only.
- *v3.0:* bidirectional request/grant handshake.
- *v4.0:* self-refresh exit integration — update can now interleave with
  self-refresh.

**Method shape:**
```python
def update_request(self, bus, state) -> UpdateEvent | None: ...
def update_grant(self, bus, state) -> None: ...
```

Two methods because request and grant travel in opposite directions — the BFM
may be sitting on either side of the interface.

**Inheritance plan:**
- `DFIv2_1Behavior` — MC-initiated only, single-cycle.
- `DFIv3_0Behavior` — full request/grant handshake.
- `DFIv4_0Behavior` — adds the self-refresh exit branching.

**Open questions:**
- Does `UpdateEvent` carry enough state to express "request denied" vs "grant
  pending"? Probably needs a small state-machine enum.

---

### 3. PHY Master / PHY Managed Interface

**What it is:** a PHY-owned mode where the PHY drives parts of the DFI bus
itself — for autonomous calibration, refresh, or training.

**Versions:** introduced v4.0 as "PHY Master Interface". **Renamed in v5.2
to "PHY Managed Interface"** (per the v5.2 release notes: "renamed the PHY
Master Interface to the PHY Managed Interface"). Same wires; the new name
reflects expanded scope — PHY-owned operations beyond pure master mode.

**Spec references (v5.2):**
- §3.8 (PHY Managed Interface)
- §4.15 (PHY Control of the DFI Bus)
- §4.16.2 (Disconnect Protocol — PHY Managed Interface interactions)

**What shifts:**
- *Pre-v4.0:* doesn't exist. Behavior raises `NotImplementedError`.
- *v4.0:* "PHY Master Interface" — the PHY can take ownership of the bus.
- *v5.2:* renamed to "PHY Managed Interface". Whether the contract genuinely
  evolved or only the name changed needs a spec-section read in pass 2.

**Method shape:**
```python
def phy_takeover(self, bus, state) -> TakeoverEvent | None: ...
def phy_release(self, bus, state) -> None: ...
```

**Inheritance plan:**
- `DFIv2_1Behavior.phy_takeover()` → `raise NotSupportedInThisVersionError`.
- `DFIv4_0Behavior` — original PHY master semantics.
- `DFIv5_2Behavior` — only if the rename brought a real semantic shift; otherwise
  the registry collapses V5_2 onto `DFIv4_0Behavior`.

**Open questions:**
- The rename (v5.2) is **not** a behavior change on its own — same wires, same
  protocol, different name in the spec. Do we need a v5.2 subclass at all? I
  lean toward **no** — the rename is a documentation concern, not a BFM
  concern, and the registry entry for `V5_2` can point at `DFIv4_0Behavior`.
  Confirm by reading v5.2 §3.8 and §4.15 in pass 2.

---

### 4. Disconnect Protocol

**What it is:** coordinated shutdown of DFI traffic when the PHY needs to
disengage — for full PHY power-down, for instance.

**Versions:** new in v4.0.

**Spec references (v5.2):**
- §3.9 (Disconnect Protocol)
- §4.16 (DFI Disconnect Protocol — full details)

**What shifts:**
- *Pre-v4.0:* no disconnect concept. The BFM treats any attempt to use it as
  a "no such interface in this version" error.
- *v4.0:* disconnect introduced as a clean handshake.
- *v5.x+:* mostly stable; some clarifications in v5.2 around update and PHY
  Managed interactions (§4.16.1, §4.16.2).

**Method shape:**
```python
def disconnect_request(self, bus, state) -> DisconnectEvent | None: ...
def disconnect_release(self, bus, state) -> None: ...
```

**Inheritance plan:**
- `DFIv2_1Behavior` / `DFIv3_xBehavior` — raise `NotSupportedInThisVersionError`.
- `DFIv4_0Behavior` — full implementation.
- v5+ inherits unchanged unless a real semantic change turns up.

**Open questions:**
- Are the v5.2 §4.16.1 / §4.16.2 clarifications semantic shifts or just
  documentation expansion? Have to read the actual sections to tell. Flagged
  for pass 2.

---

### 5. Frequency-change handshake

**What it is:** coordinated frequency transition between MC and PHY. The spec
defines two flavors: Acknowledged and Not Acknowledged.

**Versions:** existed in v2.1 (frequency-change protocol added 24 Nov 2008,
per the v5.2 release history). Expanded several times: v3.0 added the
"frequency indicator" mention; v4.0 added the explicit "Acknowledged"
protocol split.

**Spec references (v5.2):**
- §3.5.4 (Frequency Change)
- §3.5.5 (Frequency Indicator)
- §4.11.1 (Frequency Change Protocol — Acknowledged)
- §4.11.2 (Frequency Change Request Protocol — Not Acknowledged)

**What shifts:**
- *v2.1:* single-flavor handshake (basic request).
- *v3.0:* frequency indicator signal added; the PHY can declare its current
  frequency.
- *v4.0:* Acknowledged vs Not-Acknowledged split — two distinct sub-protocols.
- *v5.x:* frequency-ratio support became multi-ratio (§4.10 — "Interface
  Signals with Frequency Ratio Systems").

**Method shape:**
```python
def freq_change(self, bus, state) -> FreqChangeEvent | None: ...
```

One method; the `FreqChangeEvent.protocol` enum field distinguishes Ack from
Not-Ack.

**Inheritance plan:**
- `DFIv2_1Behavior` — basic handshake only.
- `DFIv3_0Behavior` — adds frequency-indicator support.
- `DFIv4_0Behavior` — adds the protocol-flavor branching.
- `DFIv5_xBehavior` — adds multi-ratio handling.

**Open questions:**
- Is the multi-ratio (1:1, 1:2, 1:4) selection part of `freq_change()` or its
  own area? I lean toward its own — it affects timing more than handshake.

---

### 6. Training interface

**What it is:** PHY training sequences (read leveling, write leveling, DQ
training, CA training, and friends) coordinated via the DFI training
sub-interface.

**Versions:** introduced v3.0. v3.1 added the "PHY-Requested Training
Interface". v4.0 made DFI training optional and added per-slice read
leveling, DB training, write DQ training, CA training modifications, and the
"modified write leveling strobe".

**Spec references (v5.2):**
- §4.2 (PHY Independent Training Boot Sequence)
- (Training-specific sub-interface sections scattered across §3 and §4)

**What shifts:**
- *Pre-v3.0:* no DFI training. Behavior raises `NotImplementedError`.
- *v3.0:* MC-driven training only.
- *v3.1:* PHY-requested training mode added.
- *v4.0:* training becomes optional; per-slice read leveling; DB training;
  write DQ training added; write leveling strobe semantics changed.
- *v5.x:* LPDDR5 training (CA training adjusted for LPDDR5).

**Method shape:**
```python
def training_step(self, bus, state) -> TrainingEvent | None: ...
```

**Inheritance plan:**
- `DFIv2_1Behavior` → `NotSupportedInThisVersionError`.
- `DFIv3_0Behavior` — MC-driven training.
- `DFIv3_1Behavior` — adds PHY-requested mode.
- `DFIv4_0Behavior` — optional flag, per-slice leveling, new sequences.
- v5+ inherits with the LPDDR5 additions.

**Open questions:**
- Training is the area most likely to **need decomposition** — read leveling
  carries different state than write leveling. We may want a `TrainingPhase`
  enum and per-phase sub-methods on the base class (`training_step_read_lvl`,
  `training_step_write_lvl`, `training_step_dq`, etc.).
- This is also the area I'd most want to read in full from the v4.0 spec
  before committing to a method shape.

---

### 7. Error interface

**What it is:** the PHY-driven error reporting channel — parity errors, CRC
errors, training failures, and so on.

**Versions:** new in v3.0 (per the v5.2 release notes: "Added DDR4 DRAM
support for: CRC, CA parity timing, CRC and CA parity errors, ... error
interface, and programmable parameters").

**Spec references (v5.2):**
- §3.7 (Error Interface)
- §4.14 (Error Signaling)
- §4.12 (CA Parity, CRC Errors)

**What shifts:**
- *Pre-v3.0:* no error sub-interface. PHYs communicated errors out of band.
- *v3.0:* error interface introduced as a first-class sub-interface.
- *v5.x:* possibly expanded (CA parity error reporting may have changed).

**Method shape:**
```python
def error_event(self, bus, state) -> ErrorEvent | None: ...
```

**Inheritance plan:**
- `DFIv2_1Behavior` → returns `None` always.
- `DFIv3_0Behavior` — full implementation.
- v5+ may need expansion.

**Open questions:**
- Pre-v3.0 PHYs had no error interface. Does the BFM need an "out-of-band
  error" mechanism for those versions, or is silence acceptable? For
  verification, silence is probably fine — the testbench can sniff the
  signals directly.

---

### 8. CA Parity error path

**What it is:** command/address parity signaling for DDR4+ memories. The MC
drives a parity bit alongside the command bus; the PHY relays errors.

**Versions:** new in v3.0 (DDR4-specific). LPDDR5 may have shifted the
semantics.

**Spec references (v5.2):**
- §3.1.4 (CA Parity and Parity/CRC Errors)
- §4.12 (CA Parity Signaling and CA Parity, CRC Errors)

**What shifts:**
- *Pre-v3.0 OR non-DDR4:* no CA parity. The signal envelope already gates
  this by memory type.
- *v3.0+, DDR4:* CA parity active.
- *v5.x+, LPDDR5:* may have shifted (needs verification from the spec).

**Method shape:**
```python
def ca_parity_check(self, bus, state) -> CAParityEvent | None: ...
```

**Inheritance plan:**
- Mostly version-stable once v3.0 introduces it. Possible v5.x override for
  LPDDR5.

**Open questions:**
- CA parity is **memory-type gated**, not purely version-gated. We could
  carve out a separate axis (memory-type behavior) — but this is the **only**
  memory-type-conditional shift I see in the whole list. Probably fine to
  handle inside `DFIv3_0Behavior.ca_parity_check()` with a local
  `if self.memory_type == ...:` — that's acceptable precisely because it's
  local, not scattered.

---

## Class hierarchy sketch

```
DFIv2_1Behavior            ← all NotSupportedInThisVersionError for shifts
    │                        introduced post-v2.1
    └── DFIv3_0Behavior    ← CRC, Update rewrite, Training (MC-driven),
        │                    Error interface, CA parity, Frequency indicator
        │
        ├── DFIv3_1Behavior  ← PHY-requested training, Low-power separation
        │
        └── DFIv4_0Behavior  ← PHY Master, Disconnect, Frequency change
                               protocol split, Training (optional + per-slice),
                               Update (self-refresh exit)
            (DFIv5_2Behavior only created if the PHY Master rename has any
             genuine semantic implication — see open question below.)

VERSION_BEHAVIOR = {
    DFIVersion.V2_1: DFIv2_1Behavior,
    DFIVersion.V3_0: DFIv3_0Behavior,
    DFIVersion.V3_1: DFIv3_1Behavior,
    DFIVersion.V4_0: DFIv4_0Behavior,
    DFIVersion.V5_0: DFIv4_0Behavior,   # corrections-only release
    DFIVersion.V5_1: DFIv4_0Behavior,   # new signals (additive, no shift)
    DFIVersion.V5_2: DFIv4_0Behavior,   # rename only (no semantic shift)
    # v6.0+ is a future BFM generation; out of scope here.
}
```

The thing worth noticing: **the registry can map several versions to the same
behavior class.** v5.0 / v5.1 / v5.2 all share `DFIv4_0Behavior` because none
of them introduce a semantic shift — only signal additions (handled by the
envelope) and a rename (cosmetic). That keeps the class count at the bare
minimum.

## Cross-cutting design decisions

### State ownership

The behavior classes are **stateless** by design. Per-shift state lives on the
BFM (or a small `state` dataclass passed in) so that:

- Behavior classes can be unit-tested with synthetic state.
- A user can swap behaviors mid-simulation (say, to model a frequency change)
  without losing per-channel state.

### Custom behaviors

`DFIBase.__init__` accepts an optional `behavior` keyword that overrides the
registry lookup:

```python
base = DFIBase(..., behavior=MyCustomV5Behavior())
```

That lets users model board-specific PHY quirks without forking the registry.

### Unknown versions

If `VERSION_BEHAVIOR[some_version]` is missing, raise immediately at
construction time — fail loudly rather than silently falling back. Adding a
new revision should be a deliberate code change, never something that happens
by accident.

## Open questions to resolve before coding

1. **Method signatures.** Can every shift area really fit
   `f(self, bus, state) -> Event | None`? Training is the most at-risk —
   it may need decomposition into per-phase methods.

2. **Event type proliferation.** One `DFIEvent` parent dataclass with a `kind`
   enum, or one type per area (`CRCEvent`, `UpdateEvent`, `TrainingEvent`, …)?
   I lean toward separate types — pattern-matching reads better than enum
   branching.

3. **Memory-type axis.** CA parity is memory-type-gated. Are there others we'd
   want to factor out (separate `MemoryTypeBehavior` classes)? I don't see
   any yet, but it deserves one deliberate sweep.

4. **Phase 2 vs Phase 3.** The implementation order in the
   [project_mem_ctrl_dfi.md](../../) memory note says:
   - Phase 2: training, update, status
   - Phase 3: PHY-master, low-power, frequency change
   This catalog covers Phase 2 + Phase 3 areas. Should the behavior classes
   land in two waves (Phase 2 first, Phase 3 second), or all at once with
   stub methods for the unimplemented areas?

5. **v6+ deferred.** v6.0 is a sufficient discontinuity (dropped DDR1-4 and
   LPDDR1-4, added LPDDR6 and HBM4, expanded sub-interfaces 6→14) that it's
   treated as a future BFM generation, not an extension of this one. When we
   come back to it, expect the v6+ BFM to **inherit some pieces** — the
   address-mapping primitive, the JEDEC timing loader, the basic command
   primitives — but reorganize the behavior class tree around v6 as the new
   baseline. Not this doc's problem.

6. **Testing strategy.** Each behavior class gets its own unit test file
   (`test_dfi_v3_0_behavior.py`, etc.) that constructs the class with a mock
   bus and verifies the method outputs. Integration tests run via the full
   BFM + shim path — the pattern we already have.

## What to do with this doc

- If the architecture survives this review, the next code change is **adding
  the behavior-class skeleton** — just `DFIv2_1Behavior` with stub methods
  plus the registry — on a feature branch. Then per-area implementations land
  one PR-equivalent at a time, each with its unit tests.
- If a shift area doesn't fit, redesign before writing any code.

---

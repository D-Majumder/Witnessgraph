# Witnessgraph v0.4 Design — Deterministic Cross-Source Evidence Coverage-Gap Analysis

Status: **design-only. No implementation exists yet.** This document is
research and design for a possible future implementation phase. No source
file, test file, schema, or configuration file has been changed to produce
it. Every claim about the current data model below is grounded in direct
inspection of the repository at published HEAD
`c9c9cf1c5cb8f10999864110e7163156c4877d9a` — not from memory of prior
design documents.

**Core requirement, stated up front because it governs every decision below:
Witnessgraph must never treat "no event was observed" as proof that an
event should have existed.** Every definition, algorithm, and finding in
this document is written to make that failure mode structurally
impossible, not merely discouraged by convention.

## 1. Terminology

These seven terms are kept deliberately distinct. Conflating any two of
them is the single most likely way this feature would produce a
misleading finding.

- **Evidence absence**: the plain fact that the store contains zero
  `EvidenceItem`/`NormalizedEvent`/`TimeAssertion` records referencing a
  given time window and source. This is the *only* thing Witnessgraph can
  ever directly observe. It is a statement about the case's current
  contents, not about the world.
- **Coverage interval**: a time range within which a given source's
  evidence, as actually ingested, is temporally located. Witnessgraph can
  only ever construct this from **observed** `TimeAssertion` values (see
  §5) — it has no field anywhere that records "this source was *supposed*
  to cover this range." A coverage interval is therefore always an
  *observed-activity* interval, never a declared or expected one (see next
  term).
- **Expected coverage**: what a source *should* have recorded, had it been
  functioning/collecting normally, for some time range. **This concept has
  no representation anywhere in the current data model** — no field, no
  adapter output, no metadata declares an intended start/end for any
  source. Any design that requires "expected coverage" as input is not
  implementable today without inventing a field (see §3, Definition A, and
  §14).
- **Observed activity**: the set of `TimeAssertion`s that actually exist
  for a source, i.e. the concrete evidence of "something was recorded
  here, at this time, with this precision."
- **Gap**: as defined in this document, a *relative*, evidence-grounded
  finding — a sub-interval, strictly inside the **overlap of two or more
  sources' own observed-activity intervals**, where one source has zero
  observed activity while another source (covering that same window) has
  observed activity. A gap is never a claim about a single source's own
  quiet periods in isolation (see §3, Definition C, rejected), and never a
  claim that a source *should* have had events absent another source's
  corroborating activity in the same window.
- **Uncertainty**: the acknowledged imprecision in any timestamp, carried
  structurally today by `TimeAssertion.precision` (`exact` through
  `approximate`, each with a defined tolerance in
  `core/time_model.py::_PRECISION_TOLERANCE_SECONDS`). A gap-analysis
  algorithm must widen every event's effective coverage by its own
  tolerance before reasoning about "was anything here" — otherwise a
  merely coarse-precision timestamp masquerades as a hole in coverage.
- **Contradiction**: an existing, separate concept
  (`correlate/contradictions.py`) — two `TimeAssertion`s about the *same*
  `NormalizedEvent` whose claimed values disagree beyond their combined
  tolerance. A contradiction is a disagreement between two claims about
  one event. A gap is an absence of any claim at all, relative to another
  source's presence, over a window. See §9 for exactly how these coexist
  without being confused for one another.

## 2. Available evidence — exact inventory, no invented fields

Fields actually present today, read directly from the models:

**`EvidenceItem`** (`core/evidence.py`): `id`, `source_adapter`,
`adapter_version`, `source_locator`, `raw_content_hash`, `raw_size_bytes`,
`collected_at` (required), `observed_at` (`datetime | None`, **default
`None`**), `ingest_parameters` (`dict[str, str]`, **default `{}`**),
`chain_of_custody`.

Confirmed by grep across all three adapters (`jsonl_adapter.py`,
`csv_timeline_adapter.py`, `syslog_adapter.py`) and `ingest/pipeline.py`:
**no adapter ever passes `observed_at` or `ingest_parameters` to
`EvidenceItem.create(...)`.** Both fields exist in the schema but are
`None`/`{}` for every piece of evidence any current adapter produces. Any
design that depends on either field being populated in practice is not
implementable against the current pipeline without also changing the
adapters — out of this design's scope (§13: no new adapters; changing
existing adapters' field-population behavior is also not proposed here).

**`source_locator`** is a plain string, built as `f"{source.path}:{n}"`
(`jsonl_adapter.py:46`, `csv_timeline_adapter.py:69`,
`syslog_adapter.py:46`) — a `Path.__str__()` concatenated with a literal
colon and a 1-based line/row number. This is **not** a structured field:
there is no delimiter escaping, and on Windows a path already contains a
colon after the drive letter (e.g. `C:\Users\alice\case\events.jsonl:12`
has two colons). More importantly, **the codebase already has an explicit,
tested design decision that this string must never be reparsed**:
`report/render.py`'s own docstring states untrusted/opaque fields
including `source_locator` are "rendered exactly as stored ... never
reprocessed through pathlib/os.path," and
`test_source_locator_windows_style_path_rendered_verbatim` exists
specifically to hold that line. **This design does not parse
`source_locator` for any purpose.**

**`NormalizedEvent`**: `id`, `event_type`, `entity_ids` (never populated by
any adapter — confirmed), `attributes` (`dict[str, str]`),
`derived_from`, `created_at`.

**`TimeAssertion`**: `id`, `subject_event_id`, `value` (`datetime`,
timezone-aware, enforced by `canonical_json_bytes`'s `_json_default`),
`precision` (`TimePrecision` enum with a defined tolerance table),
`source_evidence_id`, `asserted_by` (currently always
`f"adapter:{evidence.source_adapter}"`, per `ingest/pipeline.py`'s
`_derive_time_assertion`), `created_at`.

**What this inventory rules out**: there is no field anywhere — on
`EvidenceItem`, `NormalizedEvent`, or `TimeAssertion` — that names a
distinguishable "source" at finer granularity than `source_adapter`. Two
different `.jsonl` files ingested into the same case both produce
`EvidenceItem`s with `source_adapter="jsonl"`; nothing in the model
distinguishes them as two sources versus one. **This is not a minor
caveat — a full re-analysis of exactly what this means for the whole
design is in §6, and it changes this document's recommendation (§4, §14)
from the first draft.**

## 3. Candidate gap definitions

**Definition A — gaps inside an explicitly established source coverage
interval.**
Requires a field declaring "source X is expected to cover time range
[a, b]." **No such field exists** (§2, "expected coverage"). Implementing
this would require inventing new metadata — either a new `EvidenceItem`
field, a new adapter parameter, or a new CLI flag asserting a claimed
coverage window. This is explicitly the kind of unsupported "what a source
*should* contain" assumption §13 rules out. **Not implementable against
the current model. Rejected outright, not deferred.**
- False positives: would fire for any period the analyst *guessed* was
  covered but wasn't actually collected — the risk is entirely in the
  human-supplied "expected" input being wrong, which Witnessgraph cannot
  verify.
- False negatives: a genuinely mis-declared narrow "expected" window would
  hide a real gap outside it.

**Definition B — gaps inferred from overlapping source coverage.**
For two sources, each has an observed-activity interval derived purely
from the `min`/`max` of its own `TimeAssertion.value`s (precision-widened,
§5). Where two such intervals overlap, a gap is a sub-window inside that
overlap where one source has zero (precision-widened) coverage and the
other has at least one.

This is the only one of the three definitions that reasons purely from
observed evidence in *relative* terms (never from an assumed expectation),
and would be the recommended definition **if and only if "source" can be
resolved to something semantically trustworthy** — which §6 shows is not
settled by the current data model. Definition B's own soundness is
conditional on that unresolved question, not independent of it:
- False positives: beyond the density/threshold risk (mitigated by §7's
  minimum corroborating-evidence count and minimum window size), a much
  more serious false-positive/false-negative source exists if the "source"
  grouping itself silently merges two unrelated real sources — see §6's
  adversarial analysis. A gap or non-gap finding about a group that isn't
  actually one coherent source is not analyzing the wrong window, it is
  analyzing a group that doesn't correspond to anything real.
- False negatives: a gap that exists but falls *outside* the overlap of
  any two sources' observed intervals is invisible to this definition by
  design — correctly so, since there is no corroborating evidence to
  justify flagging it at all. This remains true regardless of how "source"
  is resolved.

**Definition C — gaps inferred from event continuity/density within a
single source.**
Flag any interval within one source's own observed range where the gap
between consecutive events exceeds some multiple of that source's typical
inter-event spacing (e.g., "3× the median gap"). **Rejected for v0.4.**
This is a statistical/anomaly-style heuristic operating on a single
source's own quiet periods with no corroborating second source — exactly
the shape of reasoning §13 excludes ("machine-learning anomaly
detection") even though it needn't literally use ML to have the same
epistemic problem: a quiet period is evidence of nothing except that no
event was observed, and Definition C would present that as if it were
evidence of something missing. This directly violates this document's
core requirement.
- False positives: any legitimately quiet period (nobody logged on
  overnight, a firewall genuinely passed no traffic) is indistinguishable
  from a true collection failure using density alone.
- False negatives: a source with naturally bursty-but-complete coverage
  could have its normal bursts miscalibrate the "typical spacing"
  baseline, hiding a real gap of comparable size to the burst gaps.

## 4. Recommended definition

**Revised conclusion (see §6 for the full analysis this rests on): this
document no longer recommends shipping Definition B against
`source_adapter` as "cross-source" gap analysis.** The first draft of
this design treated `source_adapter` as an adequate, if coarse, stand-in
for source identity because it made the algorithm implementable without
a schema change. On direct re-inspection, that was the wrong reasoning
order — the question of whether a trustworthy source discriminator exists
must be settled on its own merits before a definition is chosen, not
worked backward from what the current schema happens to make easy. §6
concludes no such discriminator currently exists. Definition B remains
the *architecturally* correct shape (relative, evidence-grounded,
overlap-gated) for whenever source identity is resolved — but resolving
that is now a precondition, not a detail, and §14 changes this document's
overall recommendation from GO to NO-GO accordingly. Definition A remains
rejected outright (§3) — no field, and no plausible discriminator, could
retroactively supply "expected coverage" without inventing it.

The two conditions a sound Definition B implementation would need, stated
here so the eventual prerequisite milestone (§14) has a concrete target:
- A source-identity grouping that is semantically trustworthy — i.e., one
  where two records placed in the same group are actually justified to be
  treated as "the same source" by something more than administrative
  convenience (see §6's Alternative C).
- A gap still requires **both**: (a) the absent source's own observed
  interval to actually extend across the candidate window (i.e., the
  source was collecting both before and after the gap — otherwise this is
  just the edge of that source's own coverage, not a hole inside it), and
  (b) at least a configurable minimum number of corroborating events from
  the other source inside that exact window (default: 2, never 1 — a
  single corroborating event is too weak a basis to call anything a "gap"
  against it). This half of the definition is unaffected by the
  source-identity question and remains correct as originally specified.

## 5. Time semantics

- **`TimeAssertion.value`** is the only field used to place an event on
  the timeline for gap purposes. `EvidenceItem.collected_at` (ingest-time
  wall clock) and `observed_at` (always `None` today, §2) are **not**
  used as time-axis inputs — `collected_at` reflects when Witnessgraph
  ingested the file, not when the underlying event occurred, and using it
  would conflate "when we processed this" with "when this happened,"
  producing gaps that track ingestion batching rather than reality.
- **Precision/uncertainty**: every `TimeAssertion` is widened to
  `[value - tolerance_seconds(), value + tolerance_seconds()]` before any
  interval-overlap or coverage math, using the already-existing
  `TimeAssertion.tolerance_seconds()` (`core/time_model.py`). An
  `APPROXIMATE`-precision assertion (±6 hours) contributes a much wider
  "there was activity here" window than an `EXACT` one — this is what
  keeps a coarse-precision source from generating spurious gaps against
  itself.
- **Timezone normalization**: already solved and reused, not
  reinvented — `canonical_json_bytes`'s existing UTC-`Z` normalization
  guarantees `TimeAssertion.value` is always timezone-aware and
  comparable; the detector does all interval arithmetic in UTC, exactly
  as every other timestamp-comparison in the codebase already does
  (`disagrees_with`, `_timeline_sort_key`).
- **Missing timestamps**: a `NormalizedEvent` with no associated
  `TimeAssertion` (e.g., an unparseable/timezone-ambiguous syslog line)
  contributes **nothing** to interval or gap computation — it cannot be
  placed on the timeline, so it is neither evidence of presence nor
  evidence of absence for gap purposes. This is a distinct, worth-noting
  fact ("N pieces of evidence exist but are not temporally locatable")
  but it is explicitly **not** a gap finding, and this design does not
  propose surfacing it as one.

## 6. Source attribution — full re-analysis

The first draft of this document answered this question by picking the
field that made the algorithm implementable. That was backward. This
section asks the question straight: **does the current data model
contain any field, or combination of fields, that reliably distinguishes
one independent evidence source from another** — where "reliably" means
semantically justified by what the field actually represents, not merely
correlated with source identity by coincidence or convention.

### 6.1 Direct inspection of every candidate field

- **`EvidenceItem.source_locator`** (`f"{path}:{line_or_row}"`): the only
  field that is actually unique enough to identify a physical file, if
  its path component were extracted. But extracting it requires parsing a
  string that the codebase has an explicit, tested contract never to
  reparse (§2) — parsing it here to serve this feature would be a
  layering violation on top of an existing, deliberate design decision,
  not a neutral technical choice. **Ruled out.**
- **`EvidenceItem.source_adapter`**: identifies which of the three
  built-in adapters parsed the record. Two independently-collected files
  of the same log format share this value by construction — it answers
  "what kind of parser understood this," never "which real-world thing
  produced this." **Too coarse; conflates distinct sources whenever more
  than one source shares a format**, which direct inspection of the
  three-adapter registry shows is the *ordinary* case, not a rare edge
  case (a case with five hosts' auth logs would use the `syslog` adapter
  five times, not once).
- **`EvidenceItem.adapter_version`**: versions the parser implementation,
  not the source. Two files parsed by the same adapter version are
  exactly as indistinguishable as under `source_adapter` alone; two files
  parsed by *different* adapter versions of the same format would be
  wrongly split into separate "sources" despite plausibly being the exact
  same real-world source ingested before and after an adapter upgrade.
  **Actively worse than `source_adapter`, not merely equivalent.**
- **`EvidenceItem.collected_at`**: set once per `witnessgraph ingest`
  invocation (`datetime.now(UTC)` read once in `cli/main.py`'s `ingest`
  command, passed through unchanged to every record from that one
  invocation). This looks promising at first — two *separate* CLI
  invocations for two different files will, in ordinary interactive use,
  get different wall-clock values. Direct inspection shows this is
  **not a semantically safe discriminator**, for two independent reasons,
  both concrete rather than theoretical:
  1. This project's own test suite routinely ingests multiple, genuinely
     different sources with one shared, explicit `collected_at=NOW`
     constant (e.g. `test_golden_sample_case.py` ingests three separate
     files with the identical fixed timestamp `NOW`). Any grouping scheme
     built on `collected_at` would silently merge those three sources
     into fewer groups than one calling `ingest_source` three times
     clearly intended — the exact "two independent sources become one"
     failure this document is trying to avoid, just moved to a different
     field.
  2. Using ingest-time wall clock as a source-identity signal would
     reintroduce, at the source-attribution layer, precisely the kind of
     wall-clock-dependence v0.3 deliberately eliminated from the
     manifest/identity layer (docs/phase3-v0.3-design.md §1's second
     empirical finding: identical evidence ingested at two different
     times must be treated as identical, not as different). Two
     functionally identical cases, built by two scripts that happen to
     run at different real times, could get *different* gap-analysis
     source groupings for the same logical data — a reproducibility
     regression this project has already paid once to fix in a different
     layer. **Ruled out on both semantic and reproducibility grounds, not
     merely "fragile."**
  3. `EvidenceItem.put_evidence`'s existing merge behavior does preserve
     the *first-recorded* `collected_at` on a content-address collision
     (re-ingesting the same bytes doesn't overwrite it) — so this
     specific failure mode isn't about re-ingestion *duplicating* a
     group; it's about two genuinely different, simultaneously-authored
     sources sharing one ingestion-time stamp and being wrongly
     coalesced from the start.
- **`TimeAssertion.asserted_by`**: currently always
  `f"adapter:{source_adapter}"` — strictly derived from, and no more
  informative than, `source_adapter` itself. Not a distinct discriminator.
- **`NormalizedEvent.attributes`** (e.g. a `"host"` key, when an ingested
  JSONL record happens to carry one): this is real, per-record data that
  *could* distinguish two hosts — but only for sources whose content
  happens to include such a field, under a key this design would have to
  assume means "source identity," which is exactly the kind of
  content-dependent assumption this document's core requirement forbids
  making automatically. Attribute values are free-form, adapter-agnostic
  pass-through data with no reserved schema meaning (confirmed: `jsonl`
  passes through arbitrary top-level JSON keys verbatim; `csv_timeline`
  passes through arbitrary header columns verbatim). **Not usable as a
  general, automatic discriminator** — though see §6.3's note on this as
  a possible *human-declared*, opt-in mechanism, structurally analogous
  to Phase 2's already-deferred entity-linking helper.

### 6.2 Answer to the direct question

**No — the current data model does not contain any field that reliably
distinguishes independent evidence sources at file/host granularity.**
The only categorical field that isn't either opaque-by-contract
(`source_locator`) or content-dependent-and-unstructured (`attributes`)
is `source_adapter`, and it identifies parser type, not source instance.
This is stated plainly, per this document's instruction, rather than
worked around.

### 6.3 Three alternatives, evaluated

| | **A. `source_adapter` as source identity** | **B. Ingestion invocation (`collected_at`) as source identity** | **C. New first-class `Source` identity in the model** |
|---|---|---|---|
| Semantic correctness | Wrong in the ordinary multi-source-per-format case (§6.1) — identifies format, not origin | Wrong whenever two sources are intentionally ingested with a shared/fixed timestamp (§6.1) — identifies *when*, not *what* | Correct by construction, if and only if populated honestly at ingestion time by a human or a real upstream identifier |
| False-positive risk | High and *systematic*: every case with 2+ same-format sources silently under-counts sources | High and *unpredictable*: depends on incidental ingestion timing/scripting pattern, not on the data | Low — risk moves to whether the declared identity is itself accurate, which is an input-quality question, not an algorithmic one |
| Reproducibility | Reproducible (purely content-derived), but reproducibly wrong | **Not reproducible** in the sense that matters: two logically-identical cases built at different real times, or via different scripting conventions, can get different groupings | Reproducible, and correctly tied to content rather than process |
| Compatibility with existing cases | Fully compatible — field already exists and is already populated for every case, including v0.1/v0.2 legacy ones | Fully compatible in the sense that the field already exists, but see semantic correctness above | **Not compatible without a migration decision** — no existing case (v0.1 through this v0.3 HEAD) has this field; every prior case would need a defined fallback (see below) |
| Implementation complexity | Lowest — zero model changes | Low — zero model changes, but the grouping logic itself is more subtle to get "right" in a way that still fails semantically | Highest — new field, adapter-protocol change (again, after v0.3's raw-bytes tuple change), new required or defaulted CLI input, and an explicit compatibility policy for pre-existing cases |
| Schema impact | None | None | Additive field on `EvidenceItem` (`source_id: str \| None`, analogous in spirit to how `manifest_version` was added in v0.3 — but this one requires new *input* at ingestion time, not just a computed default) |
| Honestly "cross-source"? | **No** — it is cross-*format*, mislabeled | **No** — it is cross-*ingestion-batch*, mislabeled, and non-reproducible besides | **Yes**, but only to the extent the declared identity is trustworthy — which is a property of how it's populated, not of the algorithm consuming it |

### 6.4 The adversarial example, answered exactly

*Two different JSONL files, same `jsonl` adapter, different hosts,
overlapping timestamps.*

What Witnessgraph **can** currently and honestly infer: that some number
of `NormalizedEvent`s of type(s) determined by their JSON content exist,
each with `source_adapter="jsonl"`, each traceable via `derived_from` to
a specific, content-addressed `EvidenceItem`, each optionally carrying a
`TimeAssertion` with a stated precision. If both files happen to include
a `"host"` attribute, a human reading the report can visually distinguish
the two hosts' records — the information isn't destroyed, it's just not
structurally recognized as a *source* boundary by anything in the model.

What Witnessgraph **cannot** currently infer, structurally: that these
are two distinct sources at all. Under Alternative A (this document's
prior recommendation), both files' evidence collapses into one
`source_adapter="jsonl"` group. If host A goes quiet for two hours while
host B remains active during that same window, a gap detector using
Alternative A would see *no* gap at all — host B's continued activity
under the same group label would make the merged pseudo-source appear
continuously covered, silently hiding the real, single-host outage this
feature exists to surface. This is not a corner case this design failed
to anticipate — it is the *central* scenario Phase 2 research's "a
firewall log and a host log" framing implicitly assumed would be
distinguishable, and it is not, without at least Alternative C.

### 6.5 Coverage intervals require this to be resolved, not worked around

A "coverage interval" (§1) is only meaningful as a description of *one
source's* observed activity. If the group it's computed over secretly
contains two sources, the resulting interval describes neither of them —
it describes an artifact of the grouping choice. This is why §4 now
treats source-identity resolution as a precondition for Definition B,
not an implementation detail *within* Definition B: the algorithm in §7
is not wrong on its own terms, but every one of its outputs would be
attributed to a "source" that, in the ordinary multi-source case, does
not correspond to anything real. No amount of tuning
`MIN_CORROBORATING_EVENTS` or `MIN_GAP_SECONDS` (§7) fixes this, because
the problem is upstream of the algorithm entirely.

## 7. Algorithm

**Status: architecturally sound, but not approved for implementation
against the current model.** Everything below assumes a function
`source_of(evidence_item) -> str` that resolves a trustworthy source
identity; §6 establishes that no such function can honestly be written
against today's schema (`source_adapter` is the closest candidate and is
explicitly rejected as this function's implementation, §6.3 Alternative
A). This section is retained as the forward-looking algorithmic design
for once §14's prerequisite milestone exists, not as a plan this document
is asking to be coded now.

Deterministic, order-independent, conservative. Given a `Store` and a
trustworthy `source_of(evidence_item) -> str`:

```
CONFIG (policy, not derived from evidence -- see note below):
  MIN_CORROBORATING_EVENTS = 2   # min events required from the "present" source
  MIN_GAP_SECONDS           = configurable, no built-in default claimed
                              as objectively correct (see note)

function compute_source_intervals(store):
    # returns: dict[resolved source identity -> sorted list of (widened_start, widened_end, time_assertion_id)]
    events_by_id = {e.id: e for e in store.list_normalized_events()}
    evidence_by_id = {e.id: e for e in store.list_evidence()}
    intervals = {}
    for assertion in store.list_time_assertions():
        event = events_by_id.get(assertion.subject_event_id)
        if event is None:
            continue  # dangling reference; not this detector's concern
        source_evidence = evidence_by_id.get(assertion.source_evidence_id)
        if source_evidence is None:
            continue
        source = source_of(source_evidence)  # see §7's status note -- not source_evidence.source_adapter
        tol = assertion.tolerance_seconds()
        widened = (assertion.value - tol, assertion.value + tol, assertion.id)
        intervals.setdefault(source, []).append(widened)
    for source in intervals:
        # sort by (start, id) -- id as a deterministic tiebreaker, never
        # insertion order
        intervals[source].sort(key=lambda w: (w[0], w[2]))
    return intervals

function source_span(widened_list):
    # the source's own observed-activity interval: earliest start to latest end
    return (min(w[0] for w in widened_list), max(w[1] for w in widened_list))

function find_gaps(store, min_corroborating=MIN_CORROBORATING_EVENTS,
                    min_gap_seconds=MIN_GAP_SECONDS):
    intervals = compute_source_intervals(store)
    sources = sorted(intervals.keys())   # deterministic iteration order
    findings = []
    for i in range(len(sources)):
        for j in range(len(sources)):
            if i == j:
                continue
            absent_source, present_source = sources[i], sources[j]
            absent_events = intervals[absent_source]
            present_events = intervals[present_source]
            if not absent_events or not present_events:
                continue
            absent_span = source_span(absent_events)
            present_span = source_span(present_events)
            overlap_start = max(absent_span[0], present_span[0])
            overlap_end = min(absent_span[1], present_span[1])
            if overlap_start >= overlap_end:
                continue  # no overlap at all -- Definition B's false-negative case, correctly silent

            # Candidate gap windows: consecutive-widened-interval boundaries
            # from absent_source, restricted to the overlap.
            for k in range(len(absent_events) - 1):
                gap_start = max(absent_events[k][1], overlap_start)
                gap_end = min(absent_events[k + 1][0], overlap_end)
                if gap_start >= gap_end:
                    continue
                duration = (gap_end - gap_start).total_seconds()
                if duration < min_gap_seconds:
                    continue
                corroborating = [
                    w[2] for w in present_events
                    if w[0] < gap_end and w[1] > gap_start
                ]
                if len(corroborating) < min_corroborating:
                    continue
                findings.append(GapFinding(
                    absent_source=absent_source,
                    present_source=present_source,
                    interval_start=gap_start,
                    interval_end=gap_end,
                    corroborating_time_assertion_ids=sorted(corroborating),
                    bounding_absent_assertion_ids=(absent_events[k][2], absent_events[k+1][2]),
                ))
    return sorted(findings, key=lambda f: (f.interval_start, f.absent_source, f.present_source))
```

Properties, checked against each requirement:
- **Deterministic**: every input to the algorithm (`TimeAssertion.value`,
  `.precision`, `.id`, and whatever `source_of(...)` resolves to) is
  already-stored, content-derived data; no wall-clock reads, no
  randomness — contingent on `source_of(...)` itself being deterministic,
  which is a requirement on the eventual prerequisite milestone (§14), not
  something this algorithm can guarantee on its own.
- **Order-independent**: `intervals[source].sort(...)` and the final
  `sorted(findings, ...)` both sort by content (timestamp + id), never by
  `list_time_assertions()`'s incidental return order — mirroring the
  existing `detect_time_contradictions`/`compute_manifest` pattern of
  sorting before comparing.
- **Conservative**: a gap requires the absent source's own span to
  straddle the window (boundary gaps at the very start/end of a source's
  observed activity are never flagged, since those are edge-of-coverage,
  not holes inside it — the loop only considers *consecutive* pairs of the
  absent source's own widened intervals), plus a minimum corroborating
  count, plus a minimum duration.
- **Reproducible**: identical inputs (including across export/import,
  since ids and values are unchanged by `portable.py`) produce identical,
  byte-sortable output.

**On thresholds — explicit policy, not invented objectivity**:
`MIN_CORROBORATING_EVENTS` defaults to 2 as a deliberately conservative
floor (never claim a gap on the strength of one lone corroborating
event), but this is a **policy choice**, not a value derived from the
data or from any external validation — it is marked as configurable
precisely because no current evidence justifies a single "correct"
number. `MIN_GAP_SECONDS` has **no default claimed as objectively
correct** in this document; picking one (e.g., "5 minutes") would be
smuggling in exactly the kind of unsupported assumption §13 forbids
("what a source *should* contain," restated as "how short a gap is too
short to matter"). This value must be an explicit, required
caller-supplied parameter at implementation time (CLI flag or function
argument with no default), not a constant baked into the algorithm.

## 8. Finding schema / output

**Also contingent on §6/§14**: the shape below is retained as the
forward-looking design; `absent_source`/`present_source` are whatever
`source_of(...)` resolves to once the prerequisite milestone (§14)
exists — not `EvidenceItem.source_adapter`.

No new persistent storage or schema is proposed — `GapFinding` is a
pure, in-memory `@dataclass(frozen=True)` value object, computed on
demand from the existing `Store`, exactly mirroring `TimeContradiction`'s
existing shape and lifecycle (`correlate/contradictions.py`). It is never
written to `case.db`, never included in `ProvenanceManifest` (same
reasoning as `TimeContradiction`: it's a derived analytical view over
already-manifested evidence, not itself evidence).

```python
@dataclass(frozen=True)
class GapFinding:
    absent_source: str                              # resolved source identity, see §6/§14 -- not source_adapter
    present_source: str                              # resolved source identity, see §6/§14 -- not source_adapter
    interval_start: datetime                          # UTC, precision-widened boundary
    interval_end: datetime                            # UTC, precision-widened boundary
    corroborating_time_assertion_ids: tuple[str, ...]  # >= MIN_CORROBORATING_EVENTS, sorted
    bounding_absent_assertion_ids: tuple[str, str]     # the two absent-source assertions that bracket the gap
```

Every field maps directly to something already in the store — a caller
can independently re-verify any finding by looking up those exact ids.
There is no free-text "explanation" field and no severity/confidence
score: this design deliberately does not invent a qualitative judgment
the underlying data doesn't support (see §14's "empirical, not logically
guaranteed" list — a numeric confidence score would misrepresent this).

## 9. Interaction with contradiction detection

`TimeContradiction` and `GapFinding` are structurally disjoint and never
merged into one type or one collection:

- A contradiction requires **two assertions about the same
  `NormalizedEvent`** (`subject_event_id` equality) that disagree.
- A gap requires **the total absence of any assertion from one source**
  in a window where a different source has activity — there is no shared
  `subject_event_id` involved at all, by definition (if there were a
  second assertion about the same event, that would be a potential
  contradiction, not a gap).
- A case can validly have both kinds of findings simultaneously and they
  are reported in **separate sections** (§10) — a gap finding is never
  weakened, strengthened, or explained by a nearby contradiction, and vice
  versa, since they answer different questions ("do two sources disagree
  about the same thing" vs. "does one source say nothing while another
  says something").

## 10. Reporting

No redesign of `report/render.py`'s existing architecture. A new,
optional section — `## Coverage Gaps` — is added using the exact same
pattern already established for `## Contradictions`
(`_render_contradictions`): a pure function taking a `Store`, sorted
deterministically, rendered through the existing `_untrusted`/`_code_span`
neutralization helpers for any string field, `_format_datetime` for every
timestamp, with `(none)` for the empty case. `render_report`'s section
list gains one entry; the Integrity Summary's coverage-boundary
disclosure text is extended with one sentence noting gap/contradiction
findings are both excluded from the manifest hash, matching the existing
wording style for `TimeContradiction`. The report's byte-determinism and
Unicode-neutralization contracts (`docs/phase2-v0.2-spec.md`) are
unaffected — no new untrusted-string field type is introduced beyond what
already exists (a resolved source-identity string, whatever the
prerequisite milestone in §14 makes it, is handled by the same
`_untrusted`/short-string rendering path already used for
`event_type`/`asserted_by` elsewhere).

## 11. Adversarial test cases

Each maps to a specific, concrete test to write before implementation:

1. **Genuinely non-overlapping sources**: source A active 09:00–10:00,
   source B active 14:00–15:00 → zero findings (no overlap at all, §7's
   `overlap_start >= overlap_end` short-circuit).
2. **Overlapping sources, no actual gap**: both sources have continuous
   activity throughout the overlap window → zero findings (no consecutive
   pair in the "absent" source's own timeline has a large enough hole).
3. **True internal gap**: source A has events at 09:00, 09:05, then
   nothing until 09:40, then 09:45; source B has 3+ events between
   09:10–09:35 → exactly one finding, `interval_start≈09:05`,
   `interval_end≈09:40` (widened by precision), bounded by the correct
   two source-A assertion ids.
4. **Sparse/bursty event streams**: source A bursts 10 events in one
   second, then is quiet for an hour, source B has continuous coverage
   through the quiet hour → the burst must not suppress detection of the
   subsequent real gap (bursts only affect that burst's own tiny interval,
   not the algorithm's window logic elsewhere).
5. **Identical timestamps**: two `TimeAssertion`s (different sources) with
   the exact same `value` → both correctly attributed to their own
   source's interval; no divide-by-zero or degenerate-interval crash when
   `start == end` for a single-event source (`source_span` must handle a
   one-element list).
6. **Timestamp precision differences**: an `APPROXIMATE` (±6h) assertion
   from source A must widen enough to swallow a nearby small gap that a
   `SECOND`-precision source B would otherwise flag — assert the wider
   precision suppresses a false gap that a naive point-in-time comparison
   would have produced.
7. **Timezone differences**: two assertions expressing the same instant in
   different UTC offsets must compare as identical/adjacent, not as a
   spurious multi-hour gap (already guaranteed by
   `canonical_json_bytes`'s UTC normalization, but must be asserted
   directly against `find_gaps`, not just against `canonical_json_bytes`
   in isolation).
8. **Missing timestamps**: a `NormalizedEvent` with no `TimeAssertion`
   must not appear anywhere in `compute_source_intervals`'s output and
   must not affect any interval's start/end.
9. **`collected_at` differing from `observed_at`**: construct evidence
   where `collected_at` and a real `TimeAssertion.value` differ
   significantly (simulating delayed ingestion) → assert the gap detector
   uses `TimeAssertion.value` only, never `collected_at`, by confirming
   the finding's boundaries track the assertion values regardless of what
   `collected_at` says.
10. **Reversed insertion order**: insert source B's events before source
    A's in one case, the opposite order in another otherwise-identical
    case → identical `find_gaps` output in both (order-independence,
    §7).
11. **Duplicate evidence** (re-ingesting the same source twice, per v0.3's
    idempotent `put_normalized_event`/`put_time_assertion`): assert
    `find_gaps` produces identical output before and after a redundant
    re-ingest — duplication must not be structurally possible to begin
    with (v0.3 already guarantees this at the store level), but the test
    should assert it holds through this new consumer too.
12. **Imported/exported cases**: run `find_gaps` on a case, `export_case`
    → `import_case`, run `find_gaps` again on the restored case → assert
    byte-identical `GapFinding` tuples (mirrors the existing
    export/import/report reproducibility pattern).
13. **Both contradiction and gap findings present in one case**: construct
    a case with a genuine `TimeContradiction` on one event and a genuine
    cross-source gap elsewhere → assert both are reported, in their own
    sections, and that neither detector's result set references or
    depends on the other's.

## 12. Ecosystem positioning (narrow claim)

**Wording correction from the first draft**: the earlier version of this
section stated the surveyed tools were "found to have" no such capability
— overclaiming a negative that Phase 2 research's methodology (a
documentation/feature-survey pass, not an exhaustive audit of every
tool's source and plugin ecosystem) does not actually support for every
tool listed. Corrected claim, bounded to what that research actually
established:

Per Phase 2 research (`docs/phase2-research.md`), for **Timesketch,
Plaso, OpenCTI, MISP, TheHive/Cortex, and Velociraptor**, that research
pass specifically examined each tool's documented hypothesis/inference
and correlation model and **did not identify** a structural, automatic,
evidence-cited "one source is silent while another is active" detector as
a first-class, typed output in any of them. This is a claim about what
that specific research pass did and did not identify in those six tools'
documented feature sets — not a claim that the capability is proven
absent, and not a claim extending to every tool in the broader DFIR/CTI
space. **Autopsy/Sleuth Kit is explicitly excluded from this claim**:
Phase 2 research's Autopsy entry addressed a different layer entirely
(disk-image artifact extraction) and did not examine correlation or
gap-detection capabilities at all — this document draws no conclusion
about Autopsy's capabilities in that dimension, in either direction.

- Timesketch analysts can manually notice and annotate a quiet period via
  saved searches/tagging — this is a human workflow capability Timesketch
  already supports; what that research did not identify is an automatic,
  typed, evidence-cited finding object equivalent to `GapFinding`.
- Plaso's provenance metadata could, in principle, support a similar
  analysis if someone built it on top — this document does not claim
  Plaso's architecture is incapable, only that the capability as
  described here was not identified in the surveyed tools' documented
  feature sets during that research pass.
- The differentiator claimed is specifically: this finding, if and when
  it can be honestly implemented (§14), would be (a) automatic, (b) typed
  and evidence-cited (every field traces to a real
  `TimeAssertion`/`EvidenceItem` id), and (c) produced deterministically
  from a portable, hash-verifiable case file — the combination, not any
  single element in isolation, none of which is claimed to be unique in
  the abstract, and none of which is claimed to be impossible elsewhere.

## 13. Scope boundary — explicit exclusions

This design, and any implementation of it, excludes:
- AI/LLM inference of any kind.
- Machine-learning anomaly detection (including the density/continuity
  heuristic of Definition C, rejected in §3 for the same underlying
  reason).
- Live evidence collection, network scanning, or any outbound call.
- New ingestion adapters.
- A graph database or any new storage backend.
- A web UI.
- Multi-user/collaboration features.
- Any assumption about what a source "should" contain absent another
  source's corroborating evidence in the same window (Definition A,
  rejected in §3, is exactly this and is not implemented in any form).

## 14. Go / no-go conclusion

**NO-GO for general cross-source coverage-gap analysis, as originally
scoped, against the current data model.**

This reverses the first draft's conclusion. The first draft reasoned from
"what makes the algorithm implementable today" and arrived at treating
`source_adapter` as source identity because it was available, not because
it was correct. §6's direct re-analysis shows that reasoning was
backward: no field in the current model (`source_adapter`,
`source_locator`, `adapter_version`, `collected_at`, `asserted_by`, or
content-dependent `attributes`) can honestly serve as a general source
discriminator (§6.2). Shipping Definition B against `source_adapter`
would produce a feature that is *labeled* "cross-source gap analysis" but
*is* "cross-adapter-type gap analysis" — silently wrong in exactly the
ordinary case of multiple same-format sources (§6.4), which is not a rare
edge case for a DFIR tool. Per this document's explicit instruction, the
recommendation changes rather than forcing that mislabeled version
through, and per its complementary instruction, this document does not
reach for a schema change just to rescue the original milestone shape —
§6.3's Alternative C is real but is independently substantial enough
(new field, another adapter-protocol change, a compatibility policy for
every pre-existing case) to need its own review, not to be smuggled in
here as a rider on this feature.

**Smallest technically justified prerequisite milestone**: an explicit,
analyst-declared source-identity mechanism at ingestion time — not an
automatic inference, not a parse of `source_locator`, not a reuse of
`collected_at`. Concretely, in outline only (this is not a design for
that milestone, only enough detail to make it independently schedulable
and reviewable):
- A new field, e.g. `EvidenceItem.source_id: str | None = None` —
  additive, so every v0.1/v0.2/v0.3 case remains readable unchanged (same
  pattern already proven for `ProvenanceManifest.manifest_version` in
  v0.3): a `None` value means "no declared source identity," and any
  future gap-analysis consumer must treat `None` as "not eligible for
  cross-source comparison," never as a wildcard match.
- Populated only by explicit human input at ingestion time — e.g. a new,
  optional `witnessgraph ingest <case> <adapter> <source> --source-id
  <name>` CLI argument threaded through to `EvidenceItem.create(...)` —
  never inferred, never defaulted from `source_locator` or any other
  existing field, so the "never treat absence as proof" discipline this
  document opened with extends to source identity itself: an
  undeclared source is treated as unknown, not guessed at.
- A stated compatibility policy for existing cases equivalent in spirit
  to §11's manifest-version handling: gap analysis over evidence with no
  declared `source_id` produces no findings for that evidence, explicitly
  reported as "excluded, no declared source" rather than silently grouped
  by adapter type as a fallback.
- This is real, if modest, engineering work — a new field, one new CLI
  argument, plumbing through the three adapters' `SourceDescriptor`/
  `ingest()` call sites, and its own test suite — proportionate to a
  small, separately-reviewable milestone, not proportionate to bundling
  into gap analysis's own review.

Once that milestone exists, this document's §4, §7, and §8 (already
written in terms of an abstract `source_of(...)` resolver rather than
`source_adapter`) require no further redesign — only wiring `source_of`
to the new field and lifting the "not approved for implementation" status
notes in §7/§8.

**Assumptions that remain empirical, not logically guaranteed**, carried
forward for whichever milestone is pursued next:
- That an analyst-declared `source_id` (once it exists) is accurate is an
  input-quality assumption Witnessgraph cannot itself verify — it moves
  the risk from "the algorithm guesses wrong" (today's problem) to "the
  human declares wrong" (a materially different, smaller, and more
  auditable risk, but not a zero risk).
- That `MIN_CORROBORATING_EVENTS = 2` and any chosen `min_gap_seconds`
  value are "conservative enough" to avoid false positives in real-world
  data is an empirical claim that can only be validated against real or
  realistic case data, not derived from the model itself — this document
  explicitly declines to claim either threshold is provably correct.
- That `TimeAssertion.precision` accurately reflects each adapter's true
  timestamp uncertainty is inherited, unverified, from the existing v0.1
  contradiction-detection design — this document does not re-validate
  that assumption, only reuses it consistently.

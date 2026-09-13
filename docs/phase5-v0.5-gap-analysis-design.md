# Witnessgraph v0.5 Design — Deterministic Cross-Source Evidence Coverage-Gap Analysis

Status: **design-only. No implementation exists yet.** Written against
published HEAD `77578c45ec2e815633e5f31222b08398a6c2ffaa` (v0.4, explicit
analyst-declared source identity). This document supersedes
`docs/phase4-v0.4-gap-analysis-design.md`'s NO-GO — that document's
blocker (no trustworthy source discriminator) is resolved by v0.4's
`EvidenceItem.declared_source_ids()`, confirmed by direct inspection in
this pass (see §5).

**Core requirement, unchanged and still governing every decision below:
Witnessgraph must never treat "no event was observed" as proof that an
event should have existed.**

## 1. Problem statement

An analyst who has ingested evidence from two or more independently
declared sources (e.g. two hosts' logs) currently has no automatic way
to notice that one source goes silent during a window where another,
independently-collected source shows continued activity — a pattern
worth an analyst's attention (a source outage, a logging gap, tampering,
or simply an uninteresting quiet period) that today requires manually
eyeballing the timeline. `correlate/contradictions.py` already detects
*disagreement* between two claims about the *same* event; nothing
detects *silence* from one declared source while a different declared
source has activity in the same window.

## 2. Explicit non-goals

- Not a claim that any source *should* have logged anything — see §1's
  core requirement.
- Not anomaly detection, not machine learning, not a statistical
  "unusual gap" heuristic (rejected explicitly in §7).
- Not automatic source discovery or inference — findings are only ever
  computed over sources an analyst explicitly declared via v0.4's
  `--source-id` (§5).
- Not a live-monitoring or alerting feature — this is a read-only
  analysis over an already-ingested, static case, exactly like
  `contradictions`.
- Not a confidence/probability score (§22).
- No new adapters, web UI, graph database, network API, or multi-user
  functionality — none of this design depends on any of them.

## 3. Exact user-facing purpose

`witnessgraph gaps <case>` prints a deterministic list of structural
findings of the exact shape: *"Source A has no observed evidence in
interval [X, Y) while source B has corroborating activity in that same
interval."* Each finding cites the exact evidence/time-assertion ids
that support it, so an analyst (or a third party independently verifying
the case) can check every claim against the case's own data without
trusting the tool's conclusion.

## 4. Data inputs

Exactly the fields that exist and are populated by real ingestion, per
direct inspection of `core/evidence.py`, `core/events.py`,
`core/time_model.py` at this HEAD:

- `TimeAssertion.value`, `.precision`, `.id`, `.subject_event_id`,
  `.source_evidence_id`.
- `EvidenceItem.declared_source_ids()` (v0.4) — the sole source-identity
  input.
- Nothing else. `observed_at` remains unpopulated by every adapter
  (reconfirmed by grep, unchanged since v0.4); `collected_at` is
  excluded as a time-axis input for the same reason
  `docs/phase4-v0.4-gap-analysis-design.md` §5 already gave (ingestion
  wall-clock, not event time).

## 5. Meaning of source identity

Unchanged from `docs/phase4-v0.4-source-identity-design.md` §1: an
analyst-declared assertion of common provenance, interpreted by
Witnessgraph as nothing more than an equality-comparable label.
`source_of(evidence_item)` resolves via `declared_source_ids()`:

- Exactly one distinct value → that is the resolved source.
- Zero values (no `--source-id` was ever declared for this evidence) →
  **excluded** from gap analysis, reported as excluded, never grouped
  under `source_adapter` as a fallback.
- More than one distinct value (the byte-identical-content-declared-
  under-two-different-source-ids case, §6 of the source-identity design)
  → **excluded, ambiguous**, never guessed.

This resolves the exact blocker that produced the v0.4 prerequisite's
NO-GO: two hosts' logs ingested via the same adapter are now
distinguishable, because `source_id` — not `source_adapter` — is the
grouping key.

## 6. Temporal model

Each `TimeAssertion` contributes a **widened interval**
`[value - tolerance, value + tolerance]`, using the already-existing
`TimeAssertion.tolerance_seconds()` (`core/time_model.py`,
`_PRECISION_TOLERANCE_SECONDS`, unchanged since v0.1). A source's own
observed-activity span is the union of its assertions' widened
intervals; concretely, for the boundary logic in §7, the min start and
max end across all of a source's widened intervals. This is identical in
substance to `docs/phase4-v0.4-gap-analysis-design.md` §5/§7's
already-reviewed temporal model — reused here unchanged because nothing
about it depended on the source-identity blocker that document hit.

## 7. Formal definition of a candidate gap

**Definition** (mirrors `docs/phase4-v0.4-gap-analysis-design.md` §4's
Definition B, now unblocked): for two resolved sources *A* (absent) and
*B* (present), a candidate gap is the maximal sub-interval `[gap_start,
gap_end)` strictly between two temporally-consecutive widened intervals
of *A*'s own timeline — bounded purely by *A*'s own bracketing points,
**never further clipped to *B*'s observed span** (an implementation
pitfall found and corrected during adversarial review, §23: clipping the
window to the intersection of both spans conflates "where corroboration
is possible" with "exactly *B*'s own first/last recorded instants," and
produces both false negatives when *B*'s span is narrower than the true
gap and false positives when *A* and *B* share timestamps at those
clipped edges) — such that:

1. `gap_start < gap_end` (a real, positive-duration window).
2. The window falls **strictly inside** *A*'s own observed span (never
   at or beyond either edge — an edge is "*A* stopped/hadn't started
   collecting yet," not a hole inside its coverage) — guaranteed by
   construction, since `gap_start`/`gap_end` are always two of *A*'s own
   interior bracketing points.
3. At least `MIN_CORROBORATING_EVENTS` (policy, default 2, never 1 — see
   §23) of *B*'s widened intervals overlap the window **strictly** —
   `b.start < gap_end and b.end > gap_start`, not merely touching a
   boundary. A *B* interval landing exactly on `gap_start`/`gap_end`
   coincides with an instant *A* itself already has evidence for (that
   is why it is a boundary, not part of the gap) and does not establish
   *B* activity *during* the silence — see §23's worked example.
4. `gap_end - gap_start >= MIN_GAP_SECONDS` (policy, no default claimed
   objectively correct — a required, explicit caller-supplied value).

A source-pair is skipped entirely, as a pure early-exit (not a window
clip), when *A*'s and *B*'s overall observed spans don't overlap at all
— this cannot itself produce a false negative, since if the spans truly
don't overlap, no window from *A* could ever satisfy condition 3 against
*B* regardless.

Definitions A (declared "expected coverage") and C (single-source
density/continuity heuristic) remain rejected for the exact reasons
`docs/phase4-v0.4-gap-analysis-design.md` §3 already gave — neither
depended on the source-identity blocker, so neither is revisited by
resolving it. Definition C in particular is now additionally informed by
real prior art: Timesketch ships a single-source EVTX-gap analyzer doing
almost exactly this (record-number and days-with-no-records gaps within
one log), whose own documentation explicitly warns "this analyzer will
not catch every instance... if this analyzer does not discover
something, it should not be interpreted that the records have not been
wiped" — i.e., even that tool's authors hedge against the exact
absence-as-proof error this design's core requirement forbids. This
reinforces, rather than changes, the decision to reject Definition C:
single-source density heuristics are a real, already-explored technique
with acknowledged, unresolved false-negative risk elsewhere; Witnessgraph
does not need to re-implement it to deliver a genuinely different,
cross-source, evidence-cited capability.

## 8. What counts as corroborating evidence

A `TimeAssertion` belonging to `source_of == B` whose widened interval
overlaps `[gap_start, gap_end)` (strict overlap: `w.start < gap_end and
w.end > gap_start`). Nothing else counts — not raw `EvidenceItem`s
without a `TimeAssertion` (§9), not `NormalizedEvent`s without a
`TimeAssertion`, not any content-attribute heuristic.

## 9. Boundary conditions

- Evidence with no `TimeAssertion` at all (unparseable/ambiguous
  timestamp) contributes to neither interval computation — reported
  separately as "N evidence items excluded: no time assertion," never
  silently dropped without a trace.
- Evidence with `source_of` unresolved (§5: zero or multiple declared
  ids) is excluded, reported as "N evidence items excluded: no/ambiguous
  declared source."
- A source with only one `TimeAssertion` total has no "consecutive pair"
  to form a gap between — correctly produces zero findings for that
  source as "absent," per §7 condition 2's structural requirement of at
  least two of *A*'s own assertions bracketing the window.

## 10. Minimum evidence requirements

Per §7: at least two temporally-consecutive assertions from the *absent*
source (to bracket a window), and at least `MIN_CORROBORATING_EVENTS`
(default 2) from the *present* source inside that exact window. A case
with only one declared source, or only one assertion per source,
produces zero findings — correctly, not an error.

## 11. Ambiguous/multi-source evidence

Per §5: excluded entirely from gap computation, reported in aggregate
("N evidence items excluded: ambiguous declared source") — never
resolved by picking one, never silently merged.

## 12. Missing `source_id`

Per §5: `source_of` returns unresolved; excluded, reported in aggregate,
identical treatment to a legacy (pre-v0.4) case where no evidence has
ever declared a `source_id` — that case produces zero findings and an
explicit "N evidence items excluded: no declared source" line, never a
crash and never a silent fallback to `source_adapter`.

## 13. Duplicate evidence

v0.3's idempotent `put_evidence`/`put_normalized_event`/`put_time_assertion`
already guarantee re-ingesting the same source does not duplicate
`TimeAssertion`s — `list_time_assertions()` cannot return two rows for
what is logically one observation. Gap analysis reads through the
existing `Store` protocol and inherits this guarantee without any new
code; verified directly by a regression test (§31) re-ingesting the same
fixture twice and asserting identical findings.

## 14. Overlapping intervals

Two widened intervals from the *same* source that overlap each other
(e.g. two `APPROXIMATE`-precision assertions close together) are handled
by taking `min(starts)`/`max(ends)` per §6 — the temporal model already
handles overlap correctly by construction, since it works over the union
of, not a partition of, a source's intervals.

## 15. Simultaneous events

Two assertions (from the same or different sources) with identical
`value` are two independent points in their respective sources' sorted
interval lists; the tie-break for sorting (needed for the "consecutive
pair" logic in §7) is `(start, id)`, mirroring
`docs/phase4-v0.4-gap-analysis-design.md` §7's already-reviewed pattern
— deterministic regardless of which one a database or filesystem happens
to enumerate first.

## 16. Timezone / UTC handling

Unchanged, reused without modification: `canonical_json_bytes`'s existing
UTC-`Z` normalization (`core/ids.py`) already guarantees every
`TimeAssertion.value` is timezone-aware and comparable; all interval
arithmetic in this design is performed on already-UTC-normalized
`datetime` objects, exactly as `disagrees_with`/`_timeline_sort_key`
already do elsewhere in the codebase.

## 17. Deterministic ordering

Every collection this algorithm touches is sorted by content before use:
`store.list_time_assertions()`'s incidental return order (SQLite's
`ORDER BY id`, itself just a string sort, not semantically meaningful
here) is never relied upon — intervals per source are explicitly sorted
by `(start, id)` before the consecutive-pair scan, and the final findings
list is sorted by `(interval_start, absent_source, present_source)`
before being returned or rendered. This mirrors
`compute_manifest`/`detect_time_contradictions`'s already-established
"sort before comparing" pattern exactly.

## 18. Stable finding identity

**No deterministic id is minted for a `GapFinding`.** Unlike
`NormalizedEvent`/`TimeAssertion` (which need a stable id because they
are *persisted* and referenced by other objects), a `GapFinding` is a
pure, ephemeral, recomputed-on-demand analytical view — exactly like
`TimeContradiction`, which also has no id field. Its content (the exact
tuple of `absent_source`, `present_source`, `interval_start`,
`interval_end`, and the sorted evidence ids it cites) *is* its identity
for comparison purposes; two findings are "the same" iff every field
matches. Minting a synthetic id here would imply a persistence/reference
use case this design does not have and should not invent speculatively.

## 19. Reproducibility

Directly inherited from §17's sorting discipline and from the fact that
every input (`TimeAssertion.value`/`.precision`/`.id`,
`declared_source_ids()`) is itself already fully deterministic and
export/import-stable (v0.3, v0.4). A dedicated regression test (§31)
confirms two logically-identical cases built in reversed insertion order,
and a case before/after export-import, produce byte-identical finding
sets.

## 20. Report / CLI output

**CLI**: a new `witnessgraph gaps <case> --min-gap-seconds <N>` command
(no default for `--min-gap-seconds`, per §23), mirroring `contradictions`'s
existing shape exactly (`cli/main.py`'s `contradictions` command: open
case, run detector, print lines, close case). Exit code 0 regardless of
whether findings exist (a finding is informational, not a failure —
matching `contradictions`'s existing behavior, not `verify`'s
MATCH/MISMATCH-gated exit code).

**Report**: no redesign of `report/render.py`. One new, optional
`## Coverage Gaps` section, following the exact existing pattern
`_render_contradictions` already establishes: pure function over a
`Store`, sorted deterministically, `(none)` for the empty case, every
string rendered through the existing `_untrusted()`/`_neutralize()`
pipeline. The excluded-evidence counts from §9/§11/§12 are rendered as
plain summary lines, not folded into the finding list itself.

## 21. Evidence or inference?

**Inference, not evidence** — and rendered/labeled as such, consistent
with `Hypothesis` being the system's only other inference-shaped type
(DESIGN.md principle 3/7). A `GapFinding` is never written to `case.db`,
never contributes to the provenance manifest, and is never confused with
a `TimeContradiction` (§9 of `docs/phase4-v0.4-gap-analysis-design.md`
already drew this line for contradictions; the same line applies here).
Unlike `Hypothesis`, a `GapFinding` is not analyst-authored — it is a
deterministic, mechanical inference over evidence, but it remains
structurally distinct from `EvidenceItem`/`NormalizedEvent`/
`TimeAssertion` (which represent what was observed) precisely because it
represents a *conclusion about* what was observed, not an observation
itself.

## 22. How uncertainty is represented

Structurally, not numerically: every finding's boundaries are already
precision-widened (§6), so the reported interval itself *is* the
uncertainty band, not a separate confidence score layered on top. No
probabilistic "confidence: 0.83"-style field is proposed — such a number
would imply a calibration this design has no data to justify (exactly
the concern §23 raises about thresholds generally), and would misrepresent
a purely structural, threshold-gated computation as if it were a
statistical estimate.

## 23. False-positive analysis

- **Worked example of §7's implementation pitfall, found during
  Phase 6's adversarial review of a first implementation attempt**: two
  sources, *A* and *B*, record events at the identical five-minute grid
  (09:00, 09:05, 09:10, ...), fully overlapping, no real gap anywhere.
  An initial implementation clipped each candidate window to the
  intersection of *A*'s and *B*'s overall spans and used a non-strict
  ("touching counts") corroboration test to compensate for a separate
  bug; the combination caused *every* consecutive pair of *A*'s own
  points to be reported as a "gap," because *B*'s events at the shared
  grid points exactly touched every window's boundary. The corrected
  algorithm (§7: unclipped windows, strict interior corroboration)
  produces zero findings for this case, as it must. This example is kept
  here, not just in code comments, because it is the single most
  instructive false-positive mechanism this design's own development
  surfaced — a reviewer implementing a similar detector elsewhere should
  expect the same pitfall.
- A source that is simply less active than another in a genuine, benign
  quiet period, where the quiet period nonetheless meets §7's four
  conditions, will be reported — this is the design's core, accepted
  trade-off: the finding is phrased as "no observed evidence," never as
  "nothing happened" (§1), so a benign quiet period produces a
  structurally true, if not always operationally interesting, finding.
  `MIN_GAP_SECONDS` (no built-in default, must be explicitly supplied)
  and `MIN_CORROBORATING_EVENTS` (default 2) are the only two levers to
  tune this trade-off, and neither is claimed to be objectively correct
  — restated from `docs/phase4-v0.4-gap-analysis-design.md` §7 unchanged.
- A source with sparse-but-complete coverage (long natural gaps between
  legitimate events) will be reported for every such gap that meets the
  thresholds — this is a known, accepted characteristic, not a bug;
  raising `MIN_GAP_SECONDS` is the intended lever, chosen per-case by
  the analyst, not baked in.
- Ambiguous/ungrouped evidence (§11/§12) is excluded rather than
  guessed-into a group, which trades completeness for correctness by
  design.
- **Clock skew between two independently-declared sources is not
  modeled or corrected, and cannot be from the current data model** —
  Witnessgraph has no field recording a source's clock offset relative
  to any reference, and inventing one would itself be exactly the kind
  of unsupported assumption §2 forbids. A genuine skew can therefore
  produce two symmetric failure modes: an apparent gap where none
  exists in reality (both sources were actually active, but a skewed
  clock shifted one source's timestamps outside the comparison window),
  or a masked real gap (skew coincidentally shifts a present source's
  activity to appear to overlap an absent source's true outage). This is
  a genuine, unresolved limitation, not an edge case this design
  silently handles — stated here so it is never mistaken for a solved
  problem.
- **A typo or deliberate misuse causing two genuinely different sources
  to share one declared `source_id` produces a silent false negative,
  not a crash or a false positive.** Two truly distinct sources merged
  under one label are treated as *one* resolved source (§5) — the
  detector never compares a source against itself, so a real gap in
  either one can be masked by the other's activity inside the merged
  group. This is a different, and in some ways worse, failure mode than
  the already-documented "one file, multiple logical sources" limitation
  (§34 below): that one is visible in principle (an analyst can inspect
  which file produced which records); an accidental cross-file
  `source_id` collision is not visible anywhere in the tool's own
  output, since nothing distinguishes "these records legitimately share
  a source" from "these records were mislabeled into looking like they
  do."

## 24. Adversarial cases

See §31 (test plan) for the concrete, enumerated list — restated briefly
here as the reasoning check: genuinely non-overlapping sources (zero
findings, no shared window to compare); overlapping sources with
continuous mutual coverage (zero findings); a true internal gap
(exactly one finding, correctly bounded); sparse/bursty streams (bursts
must not mask a later real gap); identical timestamps (no crash,
correct bucketing); precision differences (coarse precision must widen
enough to suppress a false gap a naive point-comparison would produce);
timezone differences (must not produce a spurious multi-hour gap);
missing timestamps (excluded, not silently dropped without a trace);
`collected_at` vs. a real `TimeAssertion.value` diverging (only the
latter drives boundaries); reversed insertion order and SQLite
insertion-order independence (§17); duplicate evidence (§13);
imported/exported cases (§19); a case with both a genuine
`TimeContradiction` and a genuine gap (§21, both reported, independently).

## 25. Performance characteristics

The algorithm is `O(S² · N log N)` where *S* is the number of distinct
resolved sources and *N* is the number of `TimeAssertion`s per source
(sorting dominates; the consecutive-pair/corroboration scan is linear
per source-pair after sorting). Given Witnessgraph's stated scale (a
handful of already-collected log files per case, per Phase 2 research —
not a live, high-volume ingestion target), this is not a practical
concern and no further optimization is proposed. A large-but-reasonable
synthetic dataset test (§31) exists to catch a real regression, not to
establish a formal performance budget the project has never needed
elsewhere.

## 26. Compatibility with existing cases

A v0.1/v0.2/v0.3 case (no `source_id` field in its stored JSON at all)
or a v0.4 case where no ingestion ever declared a `source_id`: every
`EvidenceItem.declared_source_ids()` call returns an empty set (§4 of
`docs/phase4-v0.4-source-identity-design.md`'s legacy-compatibility
finding, reused unchanged) — `witnessgraph gaps` runs without error and
reports zero findings plus an explicit "all evidence excluded: no
declared source" summary line, never a crash and never a misleading
empty-means-nothing-to-see silence.

## 27. Export / import behavior

Unaffected structurally, for the same reason `docs/phase4-v0.4-source-identity-design.md`
§11 already established for `source_id` itself: `portable.py` performs a
verbatim zip round-trip with zero JSON interpretation, so every input
this algorithm reads (`TimeAssertion`, `EvidenceItem.chain_of_custody`)
round-trips byte-for-byte. A dedicated test (§31) confirms
`find_gaps()`'s *output* is byte-identical before and after export/import,
not just inferring it from the general argument.

## 28. Manifest implications

**None, and none proposed.** `GapFinding`s are never persisted and never
enter `compute_manifest()` — identical reasoning to `TimeContradiction`'s
existing exclusion. No `manifest_version` bump is needed or justified.

## 29. Schema changes

**None.** No new SQL table, no new column, no new top-level Pydantic
model persisted to `case.db`. `GapFinding` is an in-memory,
`@dataclass(frozen=True)` value object exactly mirroring
`TimeContradiction`'s existing lifecycle.

## 30. Migration requirements

**None.** Nothing about existing data changes; nothing needs a migration
pass. This follows directly from §29 — there is no schema to migrate.

## 31. Test plan

Unit (`correlate/gaps.py`'s core logic, `Store`-level, mirroring
`test_contradictions.py`'s existing structure):
1. Empty case → zero findings, zero exclusions.
2. One declared source only → zero findings (nothing to compare against).
3. Two declared sources, non-overlapping spans → zero findings.
4. Two declared sources, same adapter, different `source_id` → correctly
   distinguished (the exact v0.4-unblocked scenario).
5. Two declared sources, different adapters, different `source_id` →
   correctly distinguished.
6. Missing `source_id` on some evidence → excluded, reported, not
   grouped by adapter.
7. Byte-identical evidence declared under two different `source_id`s →
   excluded as ambiguous.
8. Duplicate ingestion (re-ingest the same source twice) → identical
   findings before/after (§13).
9. Duplicate `NormalizedEvent`s — structurally prevented upstream by
   v0.3's idempotency; test asserts this holds through this new
   consumer, not merely inherited by assumption.
10. Overlapping intervals within one source → correctly unioned (§14).
11. Adjacent intervals (back-to-back, no gap) → zero findings for that
    pair.
12. Exact boundary equality (`gap_end == overlap_end` etc.) → correct
    `<`/`<=` boundary handling, no off-by-one false finding.
13. Events at identical timestamps → no crash, deterministic bucketing.
14. Malformed/naive-timezone temporal data — cannot occur in a
    `TimeAssertion` at all (enforced upstream by `canonical_json_bytes`'s
    existing naive-datetime rejection); test documents this structural
    guarantee rather than re-testing already-covered upstream behavior.
15. Timezone normalization — two assertions expressing the same instant
    in different offsets must not produce a spurious gap.
16. Insertion-order independence — both SQLite-store-level and
    hand-built-fake-store-level (mirroring
    `test_report_determinism.py`'s `_FakeStore` pattern), reversed
    insertion order produces identical findings.
17. Deterministic output bytes — two calls to `find_gaps()` against an
    unchanged store produce identical results; two independently-built,
    logically-identical cases produce identical results.
18. Export/import round trip preserves findings exactly (§27).
19. Legacy case (no `source_id` anywhere) → zero findings, correct
    exclusion summary, no crash (§26).
20. Insufficient corroboration (`MIN_CORROBORATING_EVENTS` not met) →
    correctly suppressed, not a finding.
21. Isolated activity (a source with no other declared source in the
    case) → zero findings for it, by construction (§10).
22. A synthetic false-positive scenario (a legitimately quiet but
    complete source) → correctly reported as a structural finding,
    verifying the "phrased as absence-of-evidence, not absence-of-event"
    wording contract (§1/§23), not that it's suppressed.
23. Unicode/control-character `source_id`s — already fully validated and
    rejected/accepted at ingestion time by v0.4; this suite only needs
    to confirm gap analysis treats a valid, already-accepted Unicode
    `source_id` as an ordinary grouping key (no special-casing needed or
    introduced).
24. Path-like `source_id` — same: already validated at ingestion,
    treated as an opaque grouping key here, never reinterpreted.
25. A large-but-reasonable synthetic dataset (a few hundred assertions
    across a handful of sources) — regression guard against an
    accidental quadratic blowup, not a formal benchmark (§25).

Integration:
26. CLI `witnessgraph gaps <case>` end-to-end, mirroring
    `test_report_cli.py`'s existing `CliRunner` pattern.
27. Report's new `## Coverage Gaps` section, deterministic across
    repeated rendering and across export/import, mirroring
    `test_report_export_import_roundtrip.py`'s existing pattern.
28. A case containing both a genuine `TimeContradiction` and a genuine
    gap finding — both reported, independently, in their own sections.

## 32. Ecosystem comparison (revised, narrower claim)

Fresh web research performed for this document (not merely re-citing
Phase 2 research verbatim) found one materially relevant, previously
unexamined fact: **Timesketch ships a real, shipping analyzer that
detects gaps within a single EVTX log** (missing Windows Event Log
record numbers, and days with no records), explicitly intended to
surface possible log clearing. Its own documentation hedges exactly the
way this design's core requirement demands: "this analyzer will not
catch every instance... if this analyzer does not discover something, it
should not be interpreted that the records have not been wiped." No
searched source (Timesketch, Plaso, OpenCTI, MISP, TheHive/Cortex,
Velociraptor, or general forensic-timeline literature on gap analysis)
surfaced a **cross-source** (two independently-declared evidence
streams), **typed, evidence-cited** finding object comparable to the
`GapFinding` design here — general forensic-timeline literature
discusses "gaps, overlaps, and outliers" as an analyst technique to
apply manually during cross-referencing, not as an automatic, typed tool
output.

## 33. Research novelty claim (carefully worded)

**Narrow, bounded claim**: Witnessgraph's proposed `GapFinding` would be,
as far as this document's research established, the first *typed,
automatic, evidence-cited, cross-source* silence/activity comparison
among the tools examined — a materially different capability from
Timesketch's existing *single-source*, record-number/day-based EVTX gap
analyzer, not a claim that gap analysis itself is novel (it plainly is
not — Timesketch already ships one, and the technique is
well-established forensic practice per the general literature found).
The specific, defensible differentiator is the combination of (a)
cross-source comparison using explicit, analyst-declared identity
(§5) rather than being confined to structural properties of one log
format, (b) every finding citing real, independently-checkable evidence
ids, and (c) deterministic, reproducible output tied to a
cryptographically-verifiable case file (v0.1–v0.4's existing
guarantees) — not any single element of that combination in isolation.

## 34. Explicit limitations

- Source-identity resolution is exactly as granular as what an analyst
  chooses to declare (`docs/phase4-v0.4-source-identity-design.md`
  §6/§14) — a single ingest invocation still cannot represent multiple
  logical sources within one file.
- No expected-coverage/uptime/reachability model exists or is proposed
  (§2) — every finding is phrased relative to another source's observed
  activity, never against an assumed baseline.
- `MIN_GAP_SECONDS` has no built-in default and must be explicitly
  chosen per case by the analyst (§7/§23) — this is a deliberate
  transfer of judgment to the human, not an oversight.
- Findings are not persisted, versioned, or citable by a stable id
  across runs beyond their own content (§18) — a future feature wanting
  to track "this specific gap finding was reviewed by an analyst" would
  need its own, separate design.
- **Clock skew between sources is not modeled or corrected** (§23) — a
  genuine, unresolved gap in what this design can guarantee, restated
  here rather than left only in the false-positive analysis.
- **Two genuinely different sources sharing one declared `source_id`
  (analyst error) silently suppresses real findings for both**, with no
  detection mechanism proposed (§23) — this is the most consequential
  residual risk in this design, precisely because it fails silently.
- **No wording or interface choice can fully prevent a human reader from
  over-interpreting "no observed evidence" as "nothing happened,"**
  despite the deliberate, structural phrasing contract (§1/§3/§21) —
  this is a residual human-factors risk this design mitigates as far as
  a tool's output text reasonably can, but does not claim to eliminate.

## 35. Recommended v0.5 scope

Implement exactly: `correlate/gaps.py` (`GapFinding` + `find_gaps`), one
CLI command (`witnessgraph gaps`), one new report section, and the full
test plan in §31. Nothing else. This is the same scope
`docs/phase4-v0.4-gap-analysis-design.md` §14's roadmap already
described as the "minimal implementation/test plan," now unblocked.

## 36. Deferred work

- A future, opt-in, per-record source-identity refinement for files that
  interleave multiple logical sources (`docs/phase4-v0.4-source-identity-design.md`
  §6) — not part of this milestone.
- A future "recompute legacy case ids" or similar migration tooling —
  irrelevant here since this design requires no migration (§30).
- Any persisted/versioned finding-tracking mechanism (§18/§34) — left
  for a future, separately-justified design if ever needed.

---

## Go / no-go

**GO.** Every open question this document raises is a policy choice
(thresholds) or an accepted, stated limitation (§34), not a blocked
prerequisite — the one genuine prerequisite (trustworthy source
identity) was resolved by the already-published v0.4 milestone and is
directly re-verified against the current code in §5. The design reuses,
without modification, every piece of machinery `docs/phase4-v0.4-gap-analysis-design.md`
already worked out (temporal widening, ordering discipline, non-goal
boundaries) and layers only the now-available source resolution on top.

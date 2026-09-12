"""v0.6: optional, analysis-time per-record source-identity refinement
for correlate.gaps.find_gaps (refine_source_by_attribute).

Every adversarial case from the approved v0.6 scope is covered here.
Uses only synthetic fixtures -- no real systems contacted or scanned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.correlate.gaps import find_gaps
from witnessgraph.portable import export_case, import_case
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _put(
    case: Case,
    *,
    source_id: str | None,
    value: datetime,
    attributes: dict[str, str] | None = None,
    label: str | None = None,
) -> TimeAssertion:
    """Insert one EvidenceItem/NormalizedEvent/TimeAssertion triple."""
    label = label or f"{source_id}-{value.isoformat()}-{attributes}"
    evidence = EvidenceItem.create(
        raw_bytes=label.encode(),
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1",
        collected_at=NOW,
        source_id=source_id,
    )
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line", attributes=attributes or {}, derived_from=(evidence.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    assertion = TimeAssertion.create(
        subject_event_id=event.id,
        value=value,
        precision=TimePrecision.EXACT,
        source_evidence_id=evidence.id,
        asserted_by="test",
        created_at=NOW,
    )
    case.store.put_time_assertion(assertion)
    return assertion


def _t(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=UTC)


# -- Default / backward compatibility ----------------------------------------


def test_default_none_reproduces_v05_behavior_exactly(tmp_path: Path) -> None:
    """The core required invariant: refine_source_by_attribute=None must be
    byte-for-byte identical to the pre-v0.6 (v0.5) result."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "real1"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "real1"})
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))

    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.refine_source_by_attribute is None
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.absent_source == "host1"
    assert finding.present_source == "host2"
    assert finding.absent_source_refinement is None
    assert finding.present_source_refinement is None
    case.close()


def test_omitting_refinement_parameter_matches_explicit_none(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))

    default_call = find_gaps(case.store, min_gap_seconds=60)
    explicit_none = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute=None)
    assert default_call == explicit_none
    case.close()


# -- Refinement subdivides a coarse source (the core new capability) --------


def test_two_real_sources_sharing_one_coarse_source_id_with_distinct_attributes(
    tmp_path: Path,
) -> None:
    """Two genuinely different real hosts accidentally sharing one declared
    source_id, but each carrying its own distinguishing 'host' attribute,
    must be correctly separable by refinement -- this is the exact case
    the v0.6 design identifies as the genuine win."""
    case = Case.create(tmp_path / "case")
    # Both declared under the SAME (colliding) source_id.
    _put(case, source_id="shared", value=_t(9, 0), attributes={"host": "real-a"})
    _put(case, source_id="shared", value=_t(9, 40), attributes={"host": "real-a"})
    _put(case, source_id="shared", value=_t(9, 10), attributes={"host": "real-b"})
    _put(case, source_id="shared", value=_t(9, 20), attributes={"host": "real-b"})

    # Without refinement: merged into one group, real-a's gap is masked.
    unrefined = find_gaps(case.store, min_gap_seconds=60)
    assert unrefined.findings == ()

    # With refinement: real-a's gap becomes visible, corroborated by real-b.
    refined = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(refined.findings) == 1
    finding = refined.findings[0]
    assert finding.absent_source == "shared"
    assert finding.absent_source_refinement == "real-a"
    assert finding.present_source == "shared"
    assert finding.present_source_refinement == "real-b"
    case.close()


def test_one_coarse_source_with_multiple_logical_sources_via_attribute(tmp_path: Path) -> None:
    """A log aggregator scenario: one declared source_id actually contains
    several real hosts distinguished only by their 'host' attribute."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="aggregator", value=_t(9, 0), attributes={"host": "h1"})
    _put(case, source_id="aggregator", value=_t(9, 40), attributes={"host": "h1"})
    _put(case, source_id="aggregator", value=_t(9, 10), attributes={"host": "h2"})
    _put(case, source_id="aggregator", value=_t(9, 20), attributes={"host": "h2"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    assert result.findings[0].absent_source_refinement == "h1"
    assert result.findings[0].present_source_refinement == "h2"
    case.close()


# -- Refinement never overrides coarse identity ------------------------------


def test_refinement_never_overrides_coarse_source_identity(tmp_path: Path) -> None:
    """Two DIFFERENT coarse source_ids that happen to share the same
    attribute value must remain distinct -- refinement can only subdivide
    a coarse group, never merge two different coarse groups together."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "same-label"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "same-label"})
    _put(case, source_id="host2", value=_t(9, 10), attributes={"host": "same-label"})
    _put(case, source_id="host2", value=_t(9, 20), attributes={"host": "same-label"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.absent_source == "host1"  # coarse identity preserved
    assert finding.present_source == "host2"  # coarse identity preserved
    assert finding.absent_source_refinement == "same-label"
    assert finding.present_source_refinement == "same-label"
    case.close()


# -- Missing / conflicting attribute values ----------------------------------


def test_missing_refining_attribute_falls_back_to_coarse_identity(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))  # no "host" attribute at all
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.absent_source == "host1"
    assert finding.absent_source_refinement is None  # fell back, not invented
    assert finding.present_source_refinement is None
    case.close()


def test_mixed_presence_of_attribute_within_one_coarse_source(tmp_path: Path) -> None:
    """Some records of a coarse source have the attribute, others don't --
    the ones without it form their own (unrefined) bucket, distinct from
    any refined subgroup."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "real-a"})
    _put(case, source_id="host1", value=_t(9, 5))  # no attribute
    _put(case, source_id="host2", value=_t(9, 2))
    _put(case, source_id="host2", value=_t(9, 3))

    # Must not crash when a coarse source has a mix of refined/unrefined records.
    result = find_gaps(case.store, min_gap_seconds=1, refine_source_by_attribute="host")
    assert isinstance(result.findings, tuple)
    case.close()


def test_unrefined_fallback_bucket_not_compared_against_own_refined_sibling(
    tmp_path: Path,
) -> None:
    """Regression for the self-comparison defect found in adversarial
    pre-commit review: a coarse source's unrefined-fallback bucket (records
    with no value for the refining attribute) must never be compared
    against a refined sibling group *from that same coarse source* -- that
    would compare the coarse source against a strict subset of itself. Both
    subgroups here have >= 2 events, enough to actually bracket a gap, so a
    pre-fix implementation would wrongly report a self-comparison finding.
    """
    case = Case.create(tmp_path / "case")
    # host1's refined "real-a" subgroup: a wide bracket, 9:00 .. 9:40.
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "real-a"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "real-a"})
    # host1's unrefined-fallback bucket: falls entirely inside that bracket.
    _put(case, source_id="host1", value=_t(9, 10))
    _put(case, source_id="host1", value=_t(9, 20))
    # host2: a genuinely different coarse source, also falling inside the
    # bracket, so a real (non-self) finding remains possible.
    _put(case, source_id="host2", value=_t(9, 12))
    _put(case, source_id="host2", value=_t(9, 18))

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")

    # The defect: host1's refined "real-a" bucket (absent) vs host1's own
    # unrefined-fallback bucket (present) -- a same-coarse-source
    # self-comparison. Must be entirely absent from the findings.
    assert not any(
        f.absent_source == "host1"
        and f.present_source == "host1"
        and f.absent_source_refinement == "real-a"
        and f.present_source_refinement is None
        for f in result.findings
    )
    # The unrefined-fallback bucket's events must be counted as excluded
    # from same-coarse-source comparison.
    assert result.excluded_unrefined_fallback_with_refined_sibling == 2
    case.close()


def test_unrefined_fallback_bucket_still_comparable_against_different_coarse_source(
    tmp_path: Path,
) -> None:
    """The self-comparison exclusion is narrowly scoped: a coarse source's
    unrefined-fallback bucket remains fully eligible to be compared against
    a genuinely different coarse source -- it is only excluded from
    comparison against a refined sibling of its own coarse source."""
    case = Case.create(tmp_path / "case")
    # host1's unrefined-fallback bucket: a wide bracket, 9:00 .. 9:40.
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    # host1's refined "real-a" subgroup, unrelated to the gap below.
    _put(case, source_id="host1", value=_t(10, 0), attributes={"host": "real-a"})
    _put(case, source_id="host1", value=_t(10, 5), attributes={"host": "real-a"})
    # host2: a genuinely different coarse source with corroborating
    # activity strictly inside host1's unrefined-fallback bracket.
    _put(case, source_id="host2", value=_t(9, 15))
    _put(case, source_id="host2", value=_t(9, 25))

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")

    assert any(
        f.absent_source == "host1"
        and f.absent_source_refinement is None
        and f.present_source == "host2"
        for f in result.findings
    )
    case.close()


def test_messy_attribute_values_are_compared_literally(tmp_path: Path) -> None:
    """Inconsistent formatting of the SAME real source's attribute (e.g.
    'Host1' vs 'host1') is treated as two distinct refined groups -- exact,
    case-sensitive comparison, no fuzzy matching (explicitly out of scope)."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "Host1"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "host1"})
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    # "Host1" and "host1" form two separate single-event refined groups for
    # host1 -- neither has 2 events to bracket a gap between, so no finding
    # from host1 as absent (this demonstrates the case-sensitivity, not a crash).
    assert all(f.absent_source != "host1" for f in result.findings)
    case.close()


# -- Duplicate evidence / idempotence -----------------------------------------


def test_duplicate_ingestion_does_not_duplicate_refined_findings(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    a1 = _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "real-a"})
    a2 = _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "real-a"})
    _put(case, source_id="host1", value=_t(9, 10), attributes={"host": "real-b"})
    _put(case, source_id="host1", value=_t(9, 20), attributes={"host": "real-b"})

    case.store.put_time_assertion(a1)  # idempotent re-insert
    case.store.put_time_assertion(a2)

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    case.close()


# -- Legacy cases -------------------------------------------------------------


def test_legacy_case_with_no_source_id_and_refinement_requested(tmp_path: Path) -> None:
    """A legacy case (no source_id declared anywhere) requesting refinement
    must still exclude via the coarse-resolution path -- refinement never
    rescues evidence that has no resolved coarse source."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id=None, value=_t(9, 0), attributes={"host": "real-a"})
    _put(case, source_id=None, value=_t(9, 40), attributes={"host": "real-a"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert result.findings == ()
    assert result.excluded_no_declared_source == 2
    case.close()


# -- Export / import -----------------------------------------------------------


def test_export_import_preserves_refined_findings_exactly(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "original")
    _put(case, source_id="shared", value=_t(9, 0), attributes={"host": "real-a"})
    _put(case, source_id="shared", value=_t(9, 40), attributes={"host": "real-a"})
    _put(case, source_id="shared", value=_t(9, 10), attributes={"host": "real-b"})
    _put(case, source_id="shared", value=_t(9, 20), attributes={"host": "real-b"})
    case.record_manifest()

    original_result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    archive = export_case(case, tmp_path / "case.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_result = find_gaps(
        restored.store, min_gap_seconds=60, refine_source_by_attribute="host"
    )
    assert restored_result.findings == original_result.findings
    restored.close()


# -- Determinism ----------------------------------------------------------------


def test_repeated_calls_with_refinement_are_identical(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="shared", value=_t(9, 0), attributes={"host": "real-a"})
    _put(case, source_id="shared", value=_t(9, 40), attributes={"host": "real-a"})
    _put(case, source_id="shared", value=_t(9, 10), attributes={"host": "real-b"})
    _put(case, source_id="shared", value=_t(9, 20), attributes={"host": "real-b"})
    first = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    second = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert first == second
    case.close()


def test_insertion_order_independence_with_refinement(tmp_path: Path) -> None:
    case_a = Case.create(tmp_path / "a")
    _put(case_a, source_id="shared", value=_t(9, 0), attributes={"host": "real-a"})
    _put(case_a, source_id="shared", value=_t(9, 40), attributes={"host": "real-a"})
    _put(case_a, source_id="shared", value=_t(9, 10), attributes={"host": "real-b"})
    _put(case_a, source_id="shared", value=_t(9, 20), attributes={"host": "real-b"})

    case_b = Case.create(tmp_path / "b")
    _put(case_b, source_id="shared", value=_t(9, 20), attributes={"host": "real-b"})
    _put(case_b, source_id="shared", value=_t(9, 10), attributes={"host": "real-b"})
    _put(case_b, source_id="shared", value=_t(9, 40), attributes={"host": "real-a"})
    _put(case_b, source_id="shared", value=_t(9, 0), attributes={"host": "real-a"})

    result_a = find_gaps(case_a.store, min_gap_seconds=60, refine_source_by_attribute="host")
    result_b = find_gaps(case_b.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert result_a.findings == result_b.findings
    case_a.close()
    case_b.close()


# -- Security: malicious / untrusted attribute values ------------------------


def test_zero_width_character_in_attribute_is_neutralized_for_grouping(tmp_path: Path) -> None:
    """A zero-width space embedded in ingested content must not silently
    make two visually-identical grouping keys compare as different, nor
    silently vanish -- it is neutralized to a visible, deterministic
    \\uXXXX placeholder before being used as a grouping key."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "real-a​"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "real-a​"})
    _put(case, source_id="host2", value=_t(9, 10), attributes={"host": "real-b"})
    _put(case, source_id="host2", value=_t(9, 20), attributes={"host": "real-b"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert "​" not in (finding.absent_source_refinement or "")
    assert "\\u200B" in (finding.absent_source_refinement or "")
    case.close()


def test_bidi_control_character_in_attribute_is_neutralized(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "host‮-a"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "host‮-a"})
    _put(case, source_id="host2", value=_t(9, 10), attributes={"host": "b"})
    _put(case, source_id="host2", value=_t(9, 20), attributes={"host": "b"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    assert "‮" not in (result.findings[0].absent_source_refinement or "")
    assert "\\u202E" in (result.findings[0].absent_source_refinement or "")
    case.close()


def test_control_character_in_attribute_is_neutralized(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "host\x01a"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "host\x01a"})
    _put(case, source_id="host2", value=_t(9, 10), attributes={"host": "b"})
    _put(case, source_id="host2", value=_t(9, 20), attributes={"host": "b"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    assert "\x01" not in (result.findings[0].absent_source_refinement or "")
    assert "\\u0001" in (result.findings[0].absent_source_refinement or "")
    case.close()


def test_neutralization_distinguishes_real_char_from_its_literal_escape_text(
    tmp_path: Path,
) -> None:
    """Regression for the neutralization-injectivity defect found in
    adversarial pre-commit review: an actual forbidden code point (e.g. a
    real U+200B zero-width space) and ingested text that merely *spells
    out* its placeholder (the literal 6 characters ``\\u200B``) must
    neutralize to two genuinely DISTINCT grouping keys -- if they collided,
    two different real hosts could be silently merged into one refined
    group. Escaping literal backslashes before substituting forbidden code
    points (fix) makes the encoding injective; without it, both values
    would neutralize to the identical string ``host\\u200B1``."""
    case = Case.create(tmp_path / "case")
    real_zero_width = "host" + "​" + "1"
    literal_escape_text = "host" + "\\u200B" + "1"
    assert real_zero_width != literal_escape_text  # sanity: genuinely different inputs

    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": real_zero_width})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": real_zero_width})
    _put(case, source_id="host1", value=_t(9, 10), attributes={"host": literal_escape_text})
    _put(case, source_id="host1", value=_t(9, 20), attributes={"host": literal_escape_text})

    result = find_gaps(case.store, min_gap_seconds=1, refine_source_by_attribute="host")

    refinements = {
        f.absent_source_refinement for f in result.findings if f.absent_source_refinement
    } | {f.present_source_refinement for f in result.findings if f.present_source_refinement}
    # A finding must exist at all (proves the two values were NOT merged
    # into one 4-event group -- with no other coarse source to compare
    # against, a collision would leave nothing to compare and produce
    # zero findings, mirroring the pre-fix bug).
    assert len(result.findings) == 1
    assert len(refinements) == 2  # two genuinely distinct neutralized keys
    case.close()


def test_path_like_attribute_value_is_treated_as_opaque_text(tmp_path: Path) -> None:
    """An attribute value that resembles a filesystem path must be used
    purely as an opaque grouping/display string -- never interpreted as
    an actual path (no existence check, no Path() coercion anywhere)."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": "/etc/passwd"})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": "/etc/passwd"})
    _put(case, source_id="host2", value=_t(9, 10), attributes={"host": "b"})
    _put(case, source_id="host2", value=_t(9, 20), attributes={"host": "b"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    assert result.findings[0].absent_source_refinement == "/etc/passwd"
    case.close()


def test_sql_shell_like_attribute_value_is_treated_as_opaque_text(tmp_path: Path) -> None:
    """An attribute value that resembles SQL/shell input must never be
    interpreted or executed -- all existing store access is already
    parameterized, and this value only ever becomes an in-memory dict key
    and a rendered/neutralized display string."""
    case = Case.create(tmp_path / "case")
    malicious = "host1'; DROP TABLE evidence_items; --"
    _put(case, source_id="host1", value=_t(9, 0), attributes={"host": malicious})
    _put(case, source_id="host1", value=_t(9, 40), attributes={"host": malicious})
    _put(case, source_id="host2", value=_t(9, 10), attributes={"host": "b"})
    _put(case, source_id="host2", value=_t(9, 20), attributes={"host": "b"})

    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    assert len(result.findings) == 1
    assert result.findings[0].absent_source_refinement == malicious
    # The store itself must still be intact and queryable.
    assert len(case.store.list_evidence()) == 4
    case.close()

"""DESIGN.md principles 3 and 7: a Hypothesis can never be evidence-free or unattributed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis, HypothesisStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REF = EvidenceRef(kind="evidence_item", id="deadbeef")


def test_hypothesis_cannot_be_constructed_without_evidence() -> None:
    """This is the structural proof that a Hypothesis cannot assert a bare fact."""
    with pytest.raises(ValidationError):
        Hypothesis(
            statement="the attacker used PowerShell", inferred_by="analyst:bob", created_at=NOW
        )


def test_hypothesis_with_only_contradicting_evidence_is_valid() -> None:
    hyp = Hypothesis(
        statement="X",
        contradicting_evidence=(REF,),
        inferred_by="analyst:bob",
        created_at=NOW,
    )
    assert len(hyp.supporting_evidence) == 0
    assert len(hyp.contradicting_evidence) == 1


def test_hypothesis_requires_non_blank_attribution() -> None:
    with pytest.raises(ValidationError):
        Hypothesis(statement="X", supporting_evidence=(REF,), inferred_by="  ", created_at=NOW)


def test_hypothesis_requires_non_blank_statement() -> None:
    with pytest.raises(ValidationError):
        Hypothesis(
            statement="  ", supporting_evidence=(REF,), inferred_by="analyst:bob", created_at=NOW
        )


def test_evidence_ref_kind_is_validated() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(kind="rumor", id="x")


def test_with_status_does_not_mutate_original_and_preserves_id() -> None:
    hyp = Hypothesis(
        statement="X", supporting_evidence=(REF,), inferred_by="analyst:bob", created_at=NOW
    )
    other_ref = EvidenceRef(kind="normalized_event", id="evt-2")
    updated = hyp.with_status(HypothesisStatus.SUPPORTED, add_supporting=(other_ref,))

    assert hyp.status == HypothesisStatus.PROPOSED
    assert updated.status == HypothesisStatus.SUPPORTED
    assert updated.id == hyp.id  # same logical hypothesis, new state
    assert len(hyp.supporting_evidence) == 1
    assert len(updated.supporting_evidence) == 2


def test_hypothesis_is_frozen() -> None:
    hyp = Hypothesis(
        statement="X", supporting_evidence=(REF,), inferred_by="analyst:bob", created_at=NOW
    )
    with pytest.raises(ValidationError):
        hyp.statement = "Y"

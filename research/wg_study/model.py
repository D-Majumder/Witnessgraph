"""Shared data model for WG-Study.

Two families of types live in this module, and neither one is ground
truth:

- ``StudyCase``/``ChainView``: participant-facing case data, at full
  fidelity (every field this module defines), built once per case from a
  WG-Bench fixture's *actual* engine output (see ``case_builder.py``).
  All ids are neutral, sequential, per-case labels (``N-01``, ``R-01``,
  ``D-01``, ``E-01``) -- never a label that itself names the fixture's
  classification (no ``SHARED_ROOT_EVIDENCE``-style id). Which subset of
  a ``StudyCase``'s fields a given condition actually shows is decided
  entirely by ``presentation.py``, never by this module.
- ``ParticipantResponse``: one recorded answer. It carries
  ``correct_answer`` because ``research/wg_study/model.py``'s own schema
  (mirroring the spec this package implements) calls for it to support
  later analysis -- this is recorded metadata on a stored response, not
  something ever displayed to a participant during the task. The
  participant-facing rendering path (``presentation.py``) never imports
  the actual ground-truth store (``answer_key.py``) at all; see that
  module's docstring and ``tests/unit/test_wg_study.py`` for the
  enforced import boundary.

Ground truth (``CaseAnswerKey``, ``PairwiseAnswer``) lives in the
physically separate ``answer_key.py`` module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Condition(str, Enum):
    """The three WG-Study presentation conditions (see
    ``docs/research/wg-study.md`` section 3)."""

    PATH_ONLY = "path_only"
    DIRECT_EVIDENCE = "direct_evidence"
    WITNESSGRAPH = "witnessgraph"


ALL_CONDITIONS: tuple[Condition, ...] = (
    Condition.PATH_ONLY,
    Condition.DIRECT_EVIDENCE,
    Condition.WITNESSGRAPH,
)


class Answer(str, Enum):
    """The three possible answers to every WG-Study question -- both the
    single question a negative-control (<2 chain) case asks and every
    pairwise question a 2+ chain case asks. See
    ``docs/research/wg-study.md`` section 4 for exact wording."""

    SHARED_ROOT = "shared_root_evidence"
    DISJOINT_ROOT = "disjoint_root_evidence"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ChainView:
    """One chain's neutral-labeled structural/evidentiary facts, at full
    fidelity. Labels only -- never a raw production id, never a label
    that encodes the fixture's classification."""

    chain_index: int
    entity_labels: tuple[str, ...]
    relationship_labels: tuple[str, ...]
    #: Raw, unresolved ``derived_from`` ids this chain's relationships
    #: cite, neutrally relabeled (``D-01``, ...). May name what was
    #: originally an EvidenceItem or a NormalizedEvent -- that
    #: indistinguishability at this level is deliberate; see
    #: ``research/wg_bench/v2/baseline2.py``.
    direct_reference_labels: tuple[str, ...]
    #: This chain's root evidence ids (after recursive NormalizedEvent
    #: resolution), neutrally relabeled (``E-01``, ...).
    root_evidence_labels: tuple[str, ...]


@dataclass(frozen=True)
class StudyCase:
    """Participant-facing case data, built once from a WG-Bench fixture's
    real engine output, then frozen and reused for every condition and
    every participant. ``case_type`` is a developer/report-facing label
    only (e.g. ``"SHARED_ROOT"``) -- it is never shown to a participant
    (see ``presentation.py``)."""

    case_id: str
    case_type: str
    source_entity_label: str
    target_entity_label: str
    path_count: int
    chains: tuple[ChainView, ...]


@dataclass(frozen=True)
class Question:
    """One question a participant answers. ``chain_pair`` is ``None``
    for the single negative-control question a <2-chain case asks;
    otherwise it is the ``(i, j)`` chain-index pair (``i < j``) a
    pairwise question asks about. WG-Study asks pairwise questions for
    *every* case with 2+ chains, not only ones with partial-overlap
    ground truth -- see ``docs/research/wg-study.md`` section 3 for why
    (this specifically avoids the question *format itself* signaling
    which fixture class a case belongs to)."""

    case_id: str
    question_id: str
    chain_pair: tuple[int, int] | None
    prompt: str


@dataclass(frozen=True)
class ParticipantResponse:
    """One recorded response. Schema matches
    ``docs/research/wg-study.md`` section 8 exactly. No name, email, or
    other identifying field -- ``participant_id`` is caller-supplied and
    is expected to be an anonymous token, never a real name or contact
    address (this module does not validate that, it is a protocol
    requirement documented in ``docs/research/wg-study.md`` section 14)."""

    participant_id: str
    condition: Condition
    case_id: str
    question_id: str
    answer: Answer
    correct_answer: Answer
    response_time_ms: int
    #: ISO-8601 UTC timestamp string.
    timestamp: str
    optional_notes: str | None
    #: True only for records produced by ``validation.py``'s developer
    #: validation mode. Must be False for every real participant
    #: response. ``analysis.analyze`` unconditionally excludes any
    #: response with this set to True from participant metrics.
    is_developer_validation: bool

"""Tests for WG-Study (``research.wg_study``) -- controlled analyst-
reasoning study *infrastructure*, not Witnessgraph production code and
not a completed human study. See ``docs/research/wg-study.md``.

Covers: answer-key isolation from the presentation layer, deterministic
condition assignment and case ordering, participant response recording
and timing, malformed/missing-response handling, metric calculations,
the "no data" analysis path, deterministic study manifest, and privacy/
data-field constraints on the stored schema.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from research.wg_study import (
    analysis,
    case_builder,
    presentation,
    runner,
    storage,
    validation,
)
from research.wg_study import (
    answer_key as answer_key_module,
)
from research.wg_study import (
    questions as questions_module,
)
from research.wg_study.model import (
    ALL_CONDITIONS,
    STUDY_VERSION,
    Answer,
    Condition,
    ParticipantResponse,
)

_CASES_AND_KEYS = case_builder.build_all_cases()
_CASES_BY_ID = {c.case_id: c for c, _k in _CASES_AND_KEYS}
_KEYS_BY_ID = {c.case_id: k for c, k in _CASES_AND_KEYS}


# ---------------------------------------------------------------------------
# Architectural isolation: presentation.py must never import answer_key.
# ---------------------------------------------------------------------------


def test_presentation_module_never_imports_answer_key() -> None:
    source = inspect.getsource(presentation)
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
            imported_names.update(f"{node.module}.{alias.name}" for alias in node.names)
    assert not any("answer_key" in name for name in imported_names), (
        f"presentation.py must never import answer_key; found imports: {imported_names}"
    )


def test_questions_module_never_imports_answer_key() -> None:
    source = inspect.getsource(questions_module)
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    assert not any("answer_key" in name for name in imported_names)


def test_case_view_never_exposes_correct_answer_field() -> None:
    """Structural guard: CaseView/ChainPresentation must have no field
    whose name could carry a ground-truth answer."""
    view = presentation.present_case(_CASES_BY_ID["wgstudy-01"], Condition.WITNESSGRAPH)
    forbidden_substrings = ("answer", "correct", "ground_truth", "disjoint_root", "shared_root")
    for field_name in view.__dataclass_fields__:
        assert not any(f in field_name.lower() for f in forbidden_substrings)
    for chain in view.chains:
        for field_name in chain.__dataclass_fields__:
            assert not any(f in field_name.lower() for f in forbidden_substrings)


# ---------------------------------------------------------------------------
# Neutral labeling: no participant-facing label may encode the answer.
# ---------------------------------------------------------------------------


def test_neutral_labels_never_encode_classification() -> None:
    forbidden = ("shared", "disjoint", "independent", "corrobor")
    for study_case, _key in _CASES_AND_KEYS:
        assert not any(f in study_case.case_id.lower() for f in forbidden), study_case.case_id
        for chain in study_case.chains:
            for label in (
                *chain.entity_labels,
                *chain.relationship_labels,
                *chain.direct_reference_labels,
                *chain.root_evidence_labels,
            ):
                assert not any(f in label.lower() for f in forbidden), label


# ---------------------------------------------------------------------------
# Condition presentation: strict no-leakage between conditions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", sorted(_CASES_BY_ID))
def test_path_only_condition_hides_all_evidence_information(case_id: str) -> None:
    view = presentation.present_case(_CASES_BY_ID[case_id], Condition.PATH_ONLY)
    for chain in view.chains:
        assert chain.direct_reference_labels is None
        assert chain.root_evidence_labels is None


@pytest.mark.parametrize("case_id", sorted(_CASES_BY_ID))
def test_direct_evidence_condition_hides_root_evidence_only(case_id: str) -> None:
    view = presentation.present_case(_CASES_BY_ID[case_id], Condition.DIRECT_EVIDENCE)
    for chain, original in zip(view.chains, _CASES_BY_ID[case_id].chains, strict=True):
        assert chain.direct_reference_labels == original.direct_reference_labels
        assert chain.root_evidence_labels is None


@pytest.mark.parametrize("case_id", sorted(_CASES_BY_ID))
def test_witnessgraph_condition_reveals_everything(case_id: str) -> None:
    view = presentation.present_case(_CASES_BY_ID[case_id], Condition.WITNESSGRAPH)
    for chain, original in zip(view.chains, _CASES_BY_ID[case_id].chains, strict=True):
        assert chain.direct_reference_labels == original.direct_reference_labels
        assert chain.root_evidence_labels == original.root_evidence_labels


def test_all_conditions_share_identical_structural_information() -> None:
    """Entities/relationships/path_count must never differ by condition
    -- only evidence-reference visibility should."""
    case = _CASES_BY_ID["wgstudy-06"]
    views = [presentation.present_case(case, c) for c in ALL_CONDITIONS]
    for view in views[1:]:
        assert view.path_count == views[0].path_count
        assert view.source_entity_label == views[0].source_entity_label
        assert view.target_entity_label == views[0].target_entity_label
        for chain, first_chain in zip(view.chains, views[0].chains, strict=True):
            assert chain.entity_labels == first_chain.entity_labels
            assert chain.relationship_labels == first_chain.relationship_labels


# ---------------------------------------------------------------------------
# Question generation.
# ---------------------------------------------------------------------------


def test_negative_control_case_gets_one_single_question() -> None:
    case = _CASES_BY_ID["wgstudy-09"]
    qs = questions_module.generate_questions(case)
    assert len(qs) == 1
    assert qs[0].chain_pair is None
    assert qs[0].question_id.endswith("-q-single")


def test_multi_chain_case_gets_all_pairwise_questions() -> None:
    case = _CASES_BY_ID["wgstudy-06"]
    qs = questions_module.generate_questions(case)
    n = len(case.chains)
    expected_pairs = {(i, j) for i in range(n) for j in range(i + 1, n)}
    assert {q.chain_pair for q in qs} == expected_pairs
    assert len(qs) == len(expected_pairs)


def test_high_multiplicity_case_gets_full_pairwise_coverage() -> None:
    case = _CASES_BY_ID["wgstudy-07"]
    qs = questions_module.generate_questions(case)
    n = len(case.chains)
    assert n == 6
    assert len(qs) == 15  # C(6, 2)


# ---------------------------------------------------------------------------
# Answer key: pairwise ground truth matches the fixture's declared partial-
# overlap structure (H3's exact A/B/C example from docs/research/wg-bench.md).
# ---------------------------------------------------------------------------


def test_partial_overlap_case_pairwise_ground_truth_is_relational_not_boolean() -> None:
    key = _KEYS_BY_ID["wgstudy-06"]
    assert len(key.pairwise_answers) == 3
    answers_by_pair = {pa.chain_pair: pa.correct_answer for pa in key.pairwise_answers}
    values = list(answers_by_pair.values())
    assert Answer.SHARED_ROOT in values
    assert Answer.DISJOINT_ROOT in values


def test_shared_root_case_every_pair_is_shared() -> None:
    key = _KEYS_BY_ID["wgstudy-01"]
    assert all(pa.correct_answer == Answer.SHARED_ROOT for pa in key.pairwise_answers)


def test_disjoint_root_case_every_pair_is_disjoint() -> None:
    key = _KEYS_BY_ID["wgstudy-02"]
    assert all(pa.correct_answer == Answer.DISJOINT_ROOT for pa in key.pairwise_answers)


def test_direct_reference_decoy_ground_truth_is_shared_despite_disjoint_direct_refs() -> None:
    """The whole point of this case: direct evidence references are
    fully disjoint (Baseline 2 would say DISJOINT), but the
    independently-authored ground truth is SHARED because both chains
    resolve to the same root -- WG-Study's answer key must reflect the
    root-evidence truth, not the direct-reference appearance."""
    case = _CASES_BY_ID["wgstudy-03"]
    key = _KEYS_BY_ID["wgstudy-03"]
    chain_a, chain_b = case.chains
    assert not set(chain_a.direct_reference_labels) & set(chain_b.direct_reference_labels)
    assert all(pa.correct_answer == Answer.SHARED_ROOT for pa in key.pairwise_answers)


def test_negative_control_answer_key_is_indeterminate() -> None:
    key = _KEYS_BY_ID["wgstudy-09"]
    assert key.whole_case_answer == Answer.INDETERMINATE
    assert key.pairwise_answers == ()


# ---------------------------------------------------------------------------
# Deterministic study manifest.
# ---------------------------------------------------------------------------


def test_case_manifest_is_deterministic_across_independent_builds() -> None:
    run_1 = case_builder.build_all_cases()
    run_2 = case_builder.build_all_cases()
    assert [c.case_id for c, _ in run_1] == [c.case_id for c, _ in run_2]
    for (case_1, key_1), (case_2, key_2) in zip(run_1, run_2, strict=True):
        assert case_1 == case_2
        assert key_1 == key_2


def test_case_manifest_has_nine_cases_one_per_type() -> None:
    types = {case_type for case_type, _fixture_id in case_builder.CASE_SELECTION}
    assert len(case_builder.CASE_SELECTION) == 9
    assert len(types) == 9


# ---------------------------------------------------------------------------
# Condition assignment / counterbalancing: deterministic and reproducible.
# ---------------------------------------------------------------------------


def test_condition_assignment_is_deterministic() -> None:
    first = runner.assign_condition("participant-alpha")
    second = runner.assign_condition("participant-alpha")
    assert first == second


def test_condition_assignment_covers_all_three_conditions_over_many_ids() -> None:
    assigned = {runner.assign_condition(f"participant-{i}") for i in range(200)}
    assert assigned == set(ALL_CONDITIONS)


def test_case_order_is_deterministic_and_a_permutation() -> None:
    case_ids = tuple(_CASES_BY_ID)
    order_1 = runner.case_order("participant-beta", case_ids)
    order_2 = runner.case_order("participant-beta", case_ids)
    assert order_1 == order_2
    assert set(order_1) == set(case_ids)


def test_case_order_differs_for_different_participants_at_least_once() -> None:
    case_ids = tuple(_CASES_BY_ID)
    orders = {runner.case_order(f"participant-{i}", case_ids) for i in range(20)}
    assert len(orders) > 1


# ---------------------------------------------------------------------------
# Response recording, timing, malformed/missing responses.
# ---------------------------------------------------------------------------


def test_record_response_stamps_correct_answer_from_answer_key(tmp_path: Path) -> None:
    response = runner.record_response(
        participant_id="participant-gamma",
        condition=Condition.WITNESSGRAPH,
        case_id="wgstudy-02",
        question_id="wgstudy-02-q-1-2",
        chain_pair=(0, 1),
        answer=Answer.DISJOINT_ROOT,
        response_time_ms=1234,
        notes=None,
        answer_keys_by_case=_KEYS_BY_ID,
    )
    assert response.correct_answer == Answer.DISJOINT_ROOT
    assert response.answer == response.correct_answer
    assert response.response_time_ms == 1234
    assert response.is_developer_validation is False


def test_record_response_rejects_unknown_chain_pair() -> None:
    with pytest.raises(KeyError):
        runner.record_response(
            participant_id="p",
            condition=Condition.PATH_ONLY,
            case_id="wgstudy-02",
            question_id="bogus",
            chain_pair=(5, 9),
            answer=Answer.INDETERMINATE,
            response_time_ms=1,
            notes=None,
            answer_keys_by_case=_KEYS_BY_ID,
        )


def test_lookup_correct_answer_missing_whole_case_answer_raises() -> None:
    multi_chain_key = _KEYS_BY_ID["wgstudy-01"]
    with pytest.raises(ValueError, match="no whole-case question"):
        runner.lookup_correct_answer(multi_chain_key, None)


def test_storage_round_trip_preserves_every_field(tmp_path: Path) -> None:
    response = ParticipantResponse(
        participant_id="anon-001",
        condition=Condition.DIRECT_EVIDENCE,
        case_id="wgstudy-01",
        question_id="wgstudy-01-q-1-2",
        answer=Answer.SHARED_ROOT,
        correct_answer=Answer.SHARED_ROOT,
        response_time_ms=4200,
        timestamp="2026-01-01T00:00:00+00:00",
        optional_notes="fast responder",
        study_version=STUDY_VERSION,
        is_developer_validation=False,
    )
    path = storage.append_response(response, out_dir=tmp_path)
    loaded = storage.load_responses(path)
    assert loaded == [response]


def test_storage_load_missing_file_returns_empty_list(tmp_path: Path) -> None:
    assert storage.load_responses(tmp_path / "does-not-exist.jsonl") == []


def test_storage_ignores_blank_lines(tmp_path: Path) -> None:
    target = tmp_path / "participant_responses.jsonl"
    response = ParticipantResponse(
        participant_id="anon-002",
        condition=Condition.PATH_ONLY,
        case_id="wgstudy-09",
        question_id="wgstudy-09-q-single",
        answer=Answer.INDETERMINATE,
        correct_answer=Answer.INDETERMINATE,
        response_time_ms=500,
        timestamp="2026-01-01T00:00:00+00:00",
        optional_notes=None,
        study_version=STUDY_VERSION,
        is_developer_validation=False,
    )
    storage.append_response(response, out_dir=tmp_path)
    with target.open("a", encoding="utf-8") as f:
        f.write("\n\n   \n")
    assert storage.load_responses(target) == [response]


def test_developer_validation_and_participant_files_are_physically_separate() -> None:
    assert storage.DEV_VALIDATION_FILE != storage.PARTICIPANT_RESPONSES_FILE
    assert storage.DEV_VALIDATION_FILE.parent == storage.PARTICIPANT_RESPONSES_FILE.parent


def test_append_response_never_uses_participant_supplied_path(tmp_path: Path) -> None:
    """`append_response` never accepts a directory string built from
    `participant_id`/`case_id` -- only an explicit `Path` (or the
    default). This test documents/pins that by constructing a
    deliberately hostile participant_id and confirming it has zero
    effect on where the file is written."""
    response = ParticipantResponse(
        participant_id="../../etc/passwd",
        condition=Condition.PATH_ONLY,
        case_id="wgstudy-01",
        question_id="q",
        answer=Answer.INDETERMINATE,
        correct_answer=Answer.INDETERMINATE,
        response_time_ms=1,
        timestamp="2026-01-01T00:00:00+00:00",
        optional_notes=None,
        study_version=STUDY_VERSION,
        is_developer_validation=False,
    )
    target = storage.append_response(response, out_dir=tmp_path)
    assert target.parent == tmp_path


# ---------------------------------------------------------------------------
# Privacy / data-field checks on the stored schema.
# ---------------------------------------------------------------------------


def test_participant_response_schema_has_no_identifying_fields() -> None:
    forbidden = ("name", "email", "address", "phone", "ip_address", "student_id")
    for field_name in ParticipantResponse.__dataclass_fields__:
        assert field_name not in forbidden, field_name


def test_participant_response_schema_matches_documented_fields() -> None:
    expected = {
        "participant_id",
        "condition",
        "case_id",
        "question_id",
        "answer",
        "correct_answer",
        "response_time_ms",
        "timestamp",
        "optional_notes",
        "study_version",
        "is_developer_validation",
    }
    assert set(ParticipantResponse.__dataclass_fields__) == expected


# ---------------------------------------------------------------------------
# Metric calculations.
# ---------------------------------------------------------------------------


def _make_response(
    condition: Condition, answer: Answer, correct: Answer, question_id: str = "case-q-1-2"
) -> ParticipantResponse:
    return ParticipantResponse(
        participant_id="p",
        condition=condition,
        case_id="case",
        question_id=question_id,
        answer=answer,
        correct_answer=correct,
        response_time_ms=1000,
        timestamp="2026-01-01T00:00:00+00:00",
        optional_notes=None,
        study_version=STUDY_VERSION,
        is_developer_validation=False,
    )


def test_analyze_with_no_data_reports_no_participant_results() -> None:
    result = analysis.analyze([])
    assert result.has_participant_data is False
    assert result.total_participant_responses == 0
    assert result.message == "No human-participant results were collected."
    assert result.per_condition == ()


def test_analyze_excludes_developer_validation_records() -> None:
    dev_only = [
        ParticipantResponse(
            participant_id="dev-validation",
            condition=Condition.WITNESSGRAPH,
            case_id="case",
            question_id="q",
            answer=Answer.SHARED_ROOT,
            correct_answer=Answer.SHARED_ROOT,
            response_time_ms=1,
            timestamp="2026-01-01T00:00:00+00:00",
            optional_notes=None,
            study_version=STUDY_VERSION,
            is_developer_validation=True,
        )
    ]
    result = analysis.analyze(dev_only)
    assert result.has_participant_data is False


def test_analyze_computes_false_corroboration_rate() -> None:
    responses = [
        _make_response(Condition.PATH_ONLY, Answer.DISJOINT_ROOT, Answer.SHARED_ROOT),
        _make_response(Condition.PATH_ONLY, Answer.SHARED_ROOT, Answer.SHARED_ROOT),
        _make_response(Condition.PATH_ONLY, Answer.DISJOINT_ROOT, Answer.DISJOINT_ROOT),
    ]
    result = analysis.analyze(responses)
    path_only = next(c for c in result.per_condition if c.condition == Condition.PATH_ONLY)
    assert path_only.response_count == 3
    assert path_only.false_corroboration_rate == pytest.approx(0.5)
    assert path_only.shared_root_accuracy == pytest.approx(0.5)
    assert path_only.disjoint_root_accuracy == pytest.approx(1.0)
    assert path_only.accuracy == pytest.approx(2 / 3)


def test_analyze_computes_response_time_statistics() -> None:
    responses = [
        _make_response(Condition.WITNESSGRAPH, Answer.SHARED_ROOT, Answer.SHARED_ROOT),
        _make_response(Condition.WITNESSGRAPH, Answer.SHARED_ROOT, Answer.SHARED_ROOT),
    ]
    result = analysis.analyze(responses)
    witnessgraph = next(c for c in result.per_condition if c.condition == Condition.WITNESSGRAPH)
    assert witnessgraph.mean_response_time_ms == pytest.approx(1000.0)
    assert witnessgraph.median_response_time_ms == pytest.approx(1000.0)


def test_analyze_indeterminate_rate() -> None:
    responses = [
        _make_response(Condition.DIRECT_EVIDENCE, Answer.INDETERMINATE, Answer.SHARED_ROOT),
        _make_response(Condition.DIRECT_EVIDENCE, Answer.DISJOINT_ROOT, Answer.DISJOINT_ROOT),
    ]
    result = analysis.analyze(responses)
    direct = next(c for c in result.per_condition if c.condition == Condition.DIRECT_EVIDENCE)
    assert direct.indeterminate_rate == pytest.approx(0.5)


def test_analyze_missing_response_rate() -> None:
    responses = [
        _make_response(Condition.WITNESSGRAPH, Answer.SHARED_ROOT, Answer.SHARED_ROOT),
    ]
    result = analysis.analyze(responses, expected_question_count_per_condition=4)
    witnessgraph = next(c for c in result.per_condition if c.condition == Condition.WITNESSGRAPH)
    assert witnessgraph.missing_response_rate == pytest.approx(0.75)
    path_only = next(c for c in result.per_condition if c.condition == Condition.PATH_ONLY)
    assert path_only.response_count == 0
    assert path_only.missing_response_rate == pytest.approx(1.0)


def test_analyze_partial_overlap_pair_accuracy_excludes_single_question() -> None:
    responses = [
        _make_response(
            Condition.WITNESSGRAPH,
            Answer.SHARED_ROOT,
            Answer.SHARED_ROOT,
            question_id="case-q-1-2",
        ),
        _make_response(
            Condition.WITNESSGRAPH,
            Answer.INDETERMINATE,
            Answer.SHARED_ROOT,
            question_id="case-q-single",
        ),
    ]
    result = analysis.analyze(responses)
    witnessgraph = next(c for c in result.per_condition if c.condition == Condition.WITNESSGRAPH)
    # only the pairwise question counts toward partial_overlap_pair_accuracy
    assert witnessgraph.partial_overlap_pair_accuracy == pytest.approx(1.0)
    # but overall accuracy includes both
    assert witnessgraph.accuracy == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Developer validation mode.
# ---------------------------------------------------------------------------


def test_developer_validation_passes_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        storage, "PARTICIPANT_RESPONSES_FILE", tmp_path / "participant_responses.jsonl"
    )
    monkeypatch.setattr(
        storage, "DEV_VALIDATION_FILE", tmp_path / "developer_validation_responses.jsonl"
    )

    result = validation.run_developer_validation()

    assert result.cases_checked == 9
    assert result.all_answers_correct_by_construction is True
    assert result.storage_round_trip_ok is True
    assert result.analysis_correctly_excludes_validation_data is True
    assert result.total_responses_recorded == result.questions_per_condition * len(ALL_CONDITIONS)
    assert not storage.PARTICIPANT_RESPONSES_FILE.exists()


# ---------------------------------------------------------------------------
# Answer-key structural sanity.
# ---------------------------------------------------------------------------


def test_answer_key_version_is_recorded_for_every_case() -> None:
    for key in _KEYS_BY_ID.values():
        assert key.answer_key_version == case_builder.ANSWER_KEY_VERSION


def test_answer_key_fixture_id_traces_to_a_real_wg_bench_fixture() -> None:
    known_fixture_ids = {fixture_id for _case_type, fixture_id in case_builder.CASE_SELECTION}
    for key in _KEYS_BY_ID.values():
        assert key.fixture_id in known_fixture_ids


def test_answer_key_module_is_the_one_place_pairwise_answer_is_defined() -> None:
    assert hasattr(answer_key_module, "PairwiseAnswer")
    assert hasattr(answer_key_module, "CaseAnswerKey")

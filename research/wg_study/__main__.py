"""python -m research.wg_study <command>

RESEARCHER commands (developer/investigator use -- see
docs/research/wg-study.md section 12 for the researcher/participant
command separation this implements):
  list-cases        Print the fixed case manifest (case id, type, path count).
  validate           Run non-interactive developer validation mode and print its result.
  pilot-walkthrough   Interactive developer/pilot walkthrough of the real
                      participant flow, revealing correct answers after each
                      response. Writes ONLY to the developer-validation
                      dataset, never the real participant dataset.
  freeze              Print the current frozen study manifest (study version,
                      case-manifest hash, condition/question definitions,
                      randomization protocol, software version).
  validate-dataset    Validate the real participant dataset file for
                      malformed/duplicate/out-of-manifest records; never
                      repairs, only reports.
  analyze             Analyze locally-stored participant responses (reports
                      "no participant results" when none exist -- see
                      ``analysis.py``).

PARTICIPANT command (no Python/repository knowledge required):
  run [--participant-id ID]
                      Runs one interactive participant session end to end:
                      instructions, condition assignment, every case in a
                      deterministic per-participant order, one question at a
                      time. Never reveals a correct answer or which condition
                      is expected to perform better. If --participant-id is
                      omitted, an anonymous token is generated and printed so
                      the participant can resume later with the same token.

This CLI never recruits participants, never simulates a participant with
an automated model, and never reads or writes anything over the network.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys

from research.wg_study import (
    analysis,
    case_builder,
    dataset_validation,
    session,
    storage,
    validation,
)
from research.wg_study import manifest as manifest_module


def _cmd_list_cases(_args: argparse.Namespace) -> int:
    cases_and_keys = case_builder.build_all_cases()
    for study_case, key in cases_and_keys:
        print(
            f"{study_case.case_id}  type={study_case.case_type}  "
            f"paths={study_case.path_count}  chains={len(study_case.chains)}  "
            f"fixture={key.fixture_id}  pairwise_questions={len(key.pairwise_answers)}"
        )
    print(f"\n{len(cases_and_keys)} cases total.")
    return 0


def _cmd_validate(_args: argparse.Namespace) -> int:
    result = validation.run_developer_validation()
    print("DEVELOPER VALIDATION (not a human-participant result)")
    print(f"  cases_checked: {result.cases_checked}")
    print(f"  questions_per_condition: {result.questions_per_condition}")
    print(f"  total_responses_recorded: {result.total_responses_recorded}")
    print(f"  all_answers_correct_by_construction: {result.all_answers_correct_by_construction}")
    print(f"  storage_round_trip_ok: {result.storage_round_trip_ok}")
    print(
        "  analysis_correctly_excludes_validation_data: "
        f"{result.analysis_correctly_excludes_validation_data}"
    )
    print(f"  detail: {result.detail}")
    ok = (
        result.all_answers_correct_by_construction
        and result.storage_round_trip_ok
        and result.analysis_correctly_excludes_validation_data
    )
    return 0 if ok else 1


def _cmd_analyze(_args: argparse.Namespace) -> int:
    responses = storage.load_responses(storage.PARTICIPANT_RESPONSES_FILE)
    result = analysis.analyze(responses)
    print(f"has_participant_data: {result.has_participant_data}")
    print(f"total_participant_responses: {result.total_participant_responses}")
    print(result.message)
    for cond_metrics in result.per_condition:
        print(f"\n[{cond_metrics.condition.value}]")
        print(f"  response_count: {cond_metrics.response_count}")
        print(f"  accuracy: {cond_metrics.accuracy}")
        print(f"  shared_root_accuracy: {cond_metrics.shared_root_accuracy}")
        print(f"  disjoint_root_accuracy: {cond_metrics.disjoint_root_accuracy}")
        print(f"  partial_overlap_pair_accuracy: {cond_metrics.partial_overlap_pair_accuracy}")
        print(f"  mean_response_time_ms: {cond_metrics.mean_response_time_ms}")
        print(f"  median_response_time_ms: {cond_metrics.median_response_time_ms}")
        print(f"  false_corroboration_rate: {cond_metrics.false_corroboration_rate}")
        print(f"  indeterminate_rate: {cond_metrics.indeterminate_rate}")
        print(f"  missing_response_rate: {cond_metrics.missing_response_rate}")
    return 0


def _cmd_freeze(_args: argparse.Namespace) -> int:
    manifest = manifest_module.build_manifest()
    print(json.dumps(manifest_module.manifest_to_dict(manifest), indent=2, sort_keys=True))
    return 0


def _cmd_validate_dataset(_args: argparse.Namespace) -> int:
    path = storage.PARTICIPANT_RESPONSES_FILE
    if not path.exists():
        print(f"no dataset file at {path} -- nothing to validate.")
        return 0
    raw_records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    report = dataset_validation.validate_dataset(
        raw_records, known_case_question_ids=manifest_module.case_question_ids()
    )
    print(f"dataset_study_version: {report.dataset_study_version}")
    print(f"total_records: {report.total_records}")
    print(f"valid_count: {report.valid_count}")
    print(f"rejected_count: {report.rejected_count}")
    for rejected in report.rejected:
        print(f"  REJECTED record #{rejected.index}: {rejected.reason}")
    return 0 if report.rejected_count == 0 else 1


def _cmd_run(args: argparse.Namespace) -> int:
    participant_id = args.participant_id or secrets.token_hex(8)
    if not args.participant_id:
        print(f"Generated anonymous participant id: {participant_id}")
        print("(record this if you need to resume the same assignment later)\n")
    summary = session.run_participant_session(participant_id=participant_id)
    print(
        f"\nparticipant_id={summary.participant_id} "
        f"cases_completed={summary.cases_completed} "
        f"questions_answered={summary.questions_answered}"
    )
    return 0


def _cmd_pilot_walkthrough(_args: argparse.Namespace) -> int:
    summary = session.run_pilot_walkthrough()
    print(
        f"\n[developer] cases_completed={summary.cases_completed} "
        f"questions_answered={summary.questions_answered}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m research.wg_study")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-cases").set_defaults(func=_cmd_list_cases)
    subparsers.add_parser("validate").set_defaults(func=_cmd_validate)
    subparsers.add_parser("analyze").set_defaults(func=_cmd_analyze)
    subparsers.add_parser("freeze").set_defaults(func=_cmd_freeze)
    subparsers.add_parser("validate-dataset").set_defaults(func=_cmd_validate_dataset)
    subparsers.add_parser("pilot-walkthrough").set_defaults(func=_cmd_pilot_walkthrough)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--participant-id", default=None)
    run_parser.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())

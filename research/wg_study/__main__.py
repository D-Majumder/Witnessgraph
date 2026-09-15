"""python -m research.wg_study <command>

Commands:
  list-cases   Print the fixed 9-case manifest (case id, type, path count).
  validate     Run developer validation mode and print its result.
  analyze      Analyze locally-stored participant responses (reports
               "no participant results" when none exist -- see
               ``analysis.py``).

This CLI never recruits, simulates, or reads any participant beyond
whatever is already in ``research/wg_study/data/participant_responses.jsonl``
on disk (nothing is in that file in this repository as of this module's
authorship). It performs no network access.
"""

from __future__ import annotations

import argparse
import sys

from research.wg_study import analysis, case_builder, storage, validation


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m research.wg_study")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-cases").set_defaults(func=_cmd_list_cases)
    subparsers.add_parser("validate").set_defaults(func=_cmd_validate)
    subparsers.add_parser("analyze").set_defaults(func=_cmd_analyze)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())

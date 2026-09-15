"""python -m research.wg_bench.v3 [--out-dir DIR]

Runs WG-Bench V3 end-to-end and prints a human-readable summary to
stdout. With ``--out-dir``, also writes ``results.json`` (canonical,
deterministic JSON) and ``results.txt`` there.

Exit code is 0 when every fixture's own hand-authored ground truth was
matched and every fixture's deterministic-replay check passed, and 1
otherwise -- independent of the discriminator-analysis results, which
are permanent experimental findings (including deliberately unfavorable
ones -- see docs/research/wg-bench.md V3 section), not pass/fail
conditions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from research.wg_bench.v3.runner import render_text_report, run_benchmark, to_json_document
from witnessgraph.core.ids import canonical_json_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m research.wg_bench.v3")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory to write results.json and results.txt into (optional).",
    )
    args = parser.parse_args(argv)

    evaluations, metrics = run_benchmark()
    report_text = render_text_report(evaluations, metrics)
    print(report_text)

    if args.out_dir is not None:
        out_dir: Path = args.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_bytes(
            canonical_json_bytes(to_json_document(evaluations, metrics))
        )
        (out_dir / "results.txt").write_text(report_text, encoding="utf-8")

    v2 = metrics.v2_style
    return 0 if v2.all_ground_truth_matches and v2.all_deterministic_replay_ok else 1


if __name__ == "__main__":
    sys.exit(main())

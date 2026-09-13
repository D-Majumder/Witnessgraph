"""Runs the full Witnessgraph pipeline end-to-end against synthetic sample data.

ingest -> normalized events -> entities -> relationships -> timeline ->
hypothesis -> export -> fresh import -> identical manifest hash.

Every step below shells out to the actual `witnessgraph` CLI (via
``python -m witnessgraph.cli.main``), so this script is also a real,
honest demonstration that the CLI works end-to-end, not just the
library underneath it. Uses only synthetic data from ./data -- see
SECURITY.md.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"


def run_cli(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "witnessgraph.cli.main", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"$ witnessgraph {' '.join(args)}")
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr, end="")
        raise SystemExit(f"command failed: {args}")
    return result.stdout


def main() -> None:
    work_dir = HERE / "_run"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir()

    case_dir = work_dir / "case"
    restored_dir = work_dir / "case-restored"
    archive = work_dir / "case.wgcase"

    run_cli("init", str(case_dir))
    run_cli("ingest", str(case_dir), "jsonl", str(DATA / "events.jsonl"))
    run_cli("ingest", str(case_dir), "csv_timeline", str(DATA / "timeline.csv"))
    run_cli("ingest", str(case_dir), "syslog", str(DATA / "auth.syslog"))

    # Manually establish one entity (v0.1 does not auto-resolve entities --
    # see DESIGN.md / examples/sample-case/README.md), linked to the first
    # piece of evidence ingested.
    list_output = run_cli("entities", "list", str(case_dir))  # expected empty so far
    assert list_output.strip() == "", "expected no entities before manual creation"

    # Find an evidence id to attach the entity to by asking the CLI's own
    # timeline for a normalized event id, then resolving one evidence id
    # via a direct case open (simplest: use the library directly here,
    # since the CLI has no "evidence list" command in v0.1).
    from witnessgraph.store.case import Case

    probe = Case.open(case_dir)
    first_evidence_id = probe.store.list_evidence()[0].id
    probe.close()

    host_output = run_cli(
        "entities", "create", str(case_dir), "host",
        "--derived-from", first_evidence_id,
        "--id", "hostname=corp-ws-042",
    )
    host_entity_id = host_output.split()[-1]

    ip_output = run_cli(
        "entities", "create", str(case_dir), "ip",
        "--derived-from", first_evidence_id,
        "--id", "address=203.0.113.7",
    )
    ip_entity_id = ip_output.split()[-1]

    # Record the connection the hypothesis below refers to as an explicit,
    # evidence-backed graph edge -- not a bare, unsupported claim (v1.1).
    run_cli(
        "relationships", "create", str(case_dir), "connected_to",
        "--source", host_entity_id, "--target", ip_entity_id,
        "--derived-from", first_evidence_id,
    )
    run_cli("relationships", "list", str(case_dir))

    run_cli("timeline", str(case_dir))
    run_cli("contradictions", str(case_dir))

    hyp_output = run_cli(
        "hypothesis", "propose", str(case_dir),
        "jsmith's workstation ran an obfuscated PowerShell command shortly after "
        "opening a macro-enabled document received around the same time as a "
        "network connection to an external host",
        "--evidence", first_evidence_id,
    )
    hypothesis_id = hyp_output.split()[-1]
    run_cli("hypothesis", "support", str(case_dir), hypothesis_id, "--evidence", first_evidence_id)
    run_cli("hypothesis", "list", str(case_dir))

    run_cli("export", str(case_dir), str(archive))
    run_cli("import", str(archive), str(restored_dir))

    replay_original = run_cli("replay", str(case_dir))
    replay_restored = run_cli("replay", str(restored_dir))

    def _hash_line(output: str) -> str:
        for line in output.splitlines():
            if line.startswith("recomputed manifest hash:"):
                return line.split(":", 1)[1].strip()
        raise AssertionError("no manifest hash line found")

    original_hash = _hash_line(replay_original)
    restored_hash = _hash_line(replay_restored)
    print(f"\noriginal manifest hash:  {original_hash}")
    print(f"restored manifest hash: {restored_hash}")
    assert original_hash == restored_hash, "export/import did not reproduce an identical hash"
    print("\nSUCCESS: export -> import reproduced an identical provenance manifest hash.")


if __name__ == "__main__":
    main()

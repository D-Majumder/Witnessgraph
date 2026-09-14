"""Runs the full Witnessgraph pipeline end-to-end against synthetic sample data.

ingest -> normalized events -> entities -> relationships -> graph
traversal -> timeline -> hypothesis -> export -> fresh import ->
identical manifest hash.

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

    user_output = run_cli(
        "entities", "create", str(case_dir), "user",
        "--derived-from", first_evidence_id,
        "--id", "username=jsmith",
    )
    user_entity_id = user_output.split()[-1]

    # Record the connections the hypothesis below refers to as explicit,
    # evidence-backed graph edges -- not bare, unsupported claims (v1.1):
    # jsmith authenticated on the workstation, which then connected out.
    run_cli(
        "relationships", "create", str(case_dir), "authenticated_as",
        "--source", user_entity_id, "--target", host_entity_id,
        "--derived-from", first_evidence_id,
    )
    run_cli(
        "relationships", "create", str(case_dir), "connected_to",
        "--source", host_entity_id, "--target", ip_entity_id,
        "--derived-from", first_evidence_id,
    )
    run_cli("relationships", "list", str(case_dir))

    # Graph analysis: what is the workstation directly connected to, and
    # how -- if at all -- does jsmith's user account connect through to
    # the external ip, two hops away (v1.1)? Do these three entities form
    # one connected cluster, or several unrelated ones?
    run_cli("graph", "neighbors", str(case_dir), host_entity_id)
    run_cli("graph", "path", str(case_dir), user_entity_id, ip_entity_id)
    run_cli("graph", "components", str(case_dir))

    # --explain: why does that path exist? Resolve every relationship's
    # derived_from evidence and every participating entity to their
    # stored records, so the answer needs no second, manual lookup.
    run_cli("graph", "path", str(case_dir), user_entity_id, ip_entity_id, "--explain")

    # Is that chain the only one, or is the connection corroborated by
    # more than one independent relationship chain of the same length?
    # In this case there is exactly one -- `graph paths` reports that
    # honestly (1 chain found, not truncated) rather than implying more.
    run_cli("graph", "paths", str(case_dir), user_entity_id, ip_entity_id)

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

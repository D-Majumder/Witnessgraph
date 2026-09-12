"""Witnessgraph CLI entry point."""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import typer

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import validate_source_id
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis, HypothesisStatus
from witnessgraph.core.time_model import TimeAssertion
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.ingest.registry import get_adapter, list_adapters
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import ReplayResult, replay_and_verify
from witnessgraph.report.render import render_report_bytes
from witnessgraph.store.case import Case

app = typer.Typer(
    help="Witnessgraph: an evidence-first, reproducible cybersecurity investigation platform.",
    no_args_is_help=True,
)
entities_app = typer.Typer(help="Inspect and create entities in a case.", no_args_is_help=True)
hypothesis_app = typer.Typer(help="Manage hypotheses in a case.", no_args_is_help=True)
app.add_typer(entities_app, name="entities")
app.add_typer(hypothesis_app, name="hypothesis")


def _resolve_evidence_ref(case: Case, ref_id: str) -> EvidenceRef:
    if case.store.get_evidence(ref_id) is not None:
        return EvidenceRef(kind="evidence_item", id=ref_id)
    if case.store.get_normalized_event(ref_id) is not None:
        return EvidenceRef(kind="normalized_event", id=ref_id)
    raise typer.BadParameter(f"{ref_id!r} is not a known EvidenceItem or NormalizedEvent id")


def _replay_verdict(result: ReplayResult) -> str:
    """Render a ReplayResult's outcome, distinguishing a real version mismatch
    from MATCH/MISMATCH -- see docs/phase3-v0.3-design.md §11."""
    if not result.version_comparable:
        assert result.recorded_manifest is not None  # only reachable when both manifests exist
        return (
            "NOT COMPARABLE (manifest algorithm version differs: "
            f"recorded=v{result.recorded_manifest.manifest_version}, "
            f"recomputed=v{result.recomputed_manifest.manifest_version})"
        )
    return "MATCH" if result.matches_recorded else "MISMATCH"


def _fail_corrupted_case(case_dir: Path) -> NoReturn:
    """Clean, non-traceback failure for a case.db that exists but cannot be
    read (not a valid SQLite database, or internally corrupted) -- see
    docs/phase2-v0.2-spec.md §14 (MAJOR 5 resolution)."""
    typer.echo(
        f"error: {case_dir} does not contain a readable Witnessgraph case database", err=True
    )
    raise typer.Exit(1)


@app.command()
def init(case_dir: Path = typer.Argument(..., help="Directory to create the new case in.")) -> None:
    """Create a new, empty case directory."""
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()
    typer.echo(f"initialized case at {case_dir}")


@app.command()
def ingest(
    case_dir: Path = typer.Argument(..., help="Case directory to ingest into."),
    adapter_id: str = typer.Argument(..., help="Adapter id, e.g. jsonl, csv_timeline, syslog."),
    source: Path = typer.Argument(..., help="Path to the evidence source file."),
    source_id: str | None = typer.Option(
        None,
        "--source-id",
        help=(
            "Explicit, analyst-declared source identity applied to every record "
            "from this ingestion (e.g. a host name). Never inferred -- omit to "
            "declare no source. See docs/phase4-v0.4-source-identity-design.md."
        ),
    ),
) -> None:
    """Ingest one evidence source file into a case using the named adapter."""
    if adapter_id not in list_adapters():
        raise typer.BadParameter(f"unknown adapter {adapter_id!r}; known: {list_adapters()}")
    if source_id is not None:
        try:
            validate_source_id(source_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--source-id") from exc
    case = Case.open(case_dir)
    adapter = get_adapter(adapter_id)
    descriptor = SourceDescriptor(path=source, source_id=source_id)
    result = ingest_source(case, adapter, descriptor, collected_at=datetime.now(UTC))
    case.record_manifest()
    case.close()
    typer.echo(
        f"ingested {result.evidence_count} evidence item(s), "
        f"{result.normalized_event_count} normalized event(s), "
        f"{result.time_assertion_count} time assertion(s)"
    )


@entities_app.command("create")
def entities_create(
    case_dir: Path,
    entity_type: str,
    derived_from: list[str] = typer.Option(
        ..., "--derived-from", help="EvidenceItem or NormalizedEvent id this entity comes from."
    ),
    identifier: list[str] = typer.Option(
        [], "--id", help="key=value identifier, e.g. --id ip=203.0.113.7"
    ),
) -> None:
    """Create an entity, explicitly linked to the evidence that established it."""
    case = Case.open(case_dir)
    for ref_id in derived_from:
        is_evidence = case.store.get_evidence(ref_id) is not None
        is_event = case.store.get_normalized_event(ref_id) is not None
        if not (is_evidence or is_event):
            case.close()
            raise typer.BadParameter(f"{ref_id!r} is not a known EvidenceItem/NormalizedEvent id")
    identifiers = dict(pair.split("=", 1) for pair in identifier)
    entity = Entity(
        entity_type=entity_type, identifiers=identifiers, derived_from=tuple(derived_from)
    )
    case.store.put_entity(entity)
    case.record_manifest()
    case.close()
    typer.echo(f"created entity {entity.id}")


@entities_app.command("list")
def entities_list(case_dir: Path) -> None:
    case = Case.open(case_dir)
    for entity in case.store.list_entities():
        typer.echo(f"{entity.id}  {entity.entity_type}  {entity.identifiers}")
    case.close()


@entities_app.command("show")
def entities_show(case_dir: Path, entity_id: str) -> None:
    case = Case.open(case_dir)
    entity = case.store.get_entity(entity_id)
    case.close()
    if entity is None:
        typer.echo(f"no such entity: {entity_id}", err=True)
        raise typer.Exit(1)
    typer.echo(entity.model_dump_json(indent=2))


@app.command()
def timeline(case_dir: Path) -> None:
    """Print all normalized events, ordered by their earliest known time assertion."""
    case = Case.open(case_dir)
    assertions_by_event: dict[str, list[TimeAssertion]] = {}
    for assertion in case.store.list_time_assertions():
        assertions_by_event.setdefault(assertion.subject_event_id, []).append(assertion)
    events = case.store.list_normalized_events()
    case.close()

    def _sort_key(event: NormalizedEvent) -> datetime:
        times = assertions_by_event.get(event.id, [])
        return min((a.value for a in times), default=event.created_at)

    for event in sorted(events, key=_sort_key):
        times = assertions_by_event.get(event.id, [])
        time_str = times[0].value.isoformat() if times else "(no time assertion)"
        typer.echo(f"{time_str}  {event.event_type}  {event.id}")


@hypothesis_app.command("propose")
def hypothesis_propose(
    case_dir: Path,
    statement: str,
    evidence_id: list[str] = typer.Option(
        ..., "--evidence", help="EvidenceItem or NormalizedEvent id supporting this hypothesis."
    ),
    inferred_by: str = typer.Option("analyst", help="Who is proposing this hypothesis."),
) -> None:
    case = Case.open(case_dir)
    refs = tuple(_resolve_evidence_ref(case, eid) for eid in evidence_id)
    hyp = Hypothesis(
        statement=statement,
        supporting_evidence=refs,
        inferred_by=inferred_by,
        created_at=datetime.now(UTC),
    )
    case.store.put_hypothesis(hyp)
    case.record_manifest()
    case.close()
    typer.echo(f"proposed hypothesis {hyp.id}")


def _change_hypothesis_status(
    case_dir: Path,
    hypothesis_id: str,
    status: HypothesisStatus,
    *,
    add_supporting_ids: list[str] | None = None,
    add_contradicting_ids: list[str] | None = None,
) -> None:
    case = Case.open(case_dir)
    existing = case.store.get_hypothesis(hypothesis_id)
    if existing is None:
        case.close()
        typer.echo(f"no such hypothesis: {hypothesis_id}", err=True)
        raise typer.Exit(1)
    add_supporting = tuple(_resolve_evidence_ref(case, i) for i in (add_supporting_ids or []))
    add_contradicting = tuple(_resolve_evidence_ref(case, i) for i in (add_contradicting_ids or []))
    updated = existing.with_status(
        status, add_supporting=add_supporting, add_contradicting=add_contradicting
    )
    case.store.put_hypothesis(updated)
    case.record_manifest()
    case.close()
    typer.echo(f"hypothesis {hypothesis_id} -> {status.value}")


@hypothesis_app.command("support")
def hypothesis_support(
    case_dir: Path,
    hypothesis_id: str,
    evidence_id: list[str] = typer.Option(..., "--evidence"),
) -> None:
    _change_hypothesis_status(
        case_dir, hypothesis_id, HypothesisStatus.SUPPORTED, add_supporting_ids=evidence_id
    )


@hypothesis_app.command("contradict")
def hypothesis_contradict(
    case_dir: Path,
    hypothesis_id: str,
    evidence_id: list[str] = typer.Option(..., "--evidence"),
) -> None:
    _change_hypothesis_status(
        case_dir, hypothesis_id, HypothesisStatus.CONTRADICTED, add_contradicting_ids=evidence_id
    )


@hypothesis_app.command("list")
def hypothesis_list(case_dir: Path) -> None:
    case = Case.open(case_dir)
    for hyp in case.store.list_hypotheses():
        typer.echo(f"{hyp.id}  [{hyp.status.value}]  {hyp.statement}")
    case.close()


@app.command()
def export(
    case_dir: Path,
    output: Path = typer.Argument(..., help="Output .wgcase archive path."),
) -> None:
    """Package a case directory into a single portable .wgcase archive."""
    case = Case.open(case_dir)
    export_case(case, output)
    case.close()
    typer.echo(f"exported {case_dir} -> {output}")


@app.command(name="import")
def import_case_cmd(
    archive: Path = typer.Argument(..., help="A .wgcase archive to import."),
    dest_dir: Path = typer.Argument(..., help="Destination directory for the restored case."),
) -> None:
    """Import a .wgcase archive into a fresh case directory."""
    try:
        case = import_case(archive, dest_dir)
    except sqlite3.DatabaseError:
        typer.echo(
            "error: the archive's case database is not readable (corrupted or invalid)",
            err=True,
        )
        raise typer.Exit(1) from None
    manifest = case.load_recorded_manifest()
    case.close()
    typer.echo(f"imported {archive} -> {dest_dir}")
    if manifest:
        typer.echo(f"manifest hash: {manifest.manifest_hash}")


@app.command()
def report(
    case_dir: Path = typer.Argument(..., help="Case directory to render a report for."),
    output: Path | None = typer.Option(
        None, "--output", help="Write the report to this file instead of stdout."
    ),
    output_format: str = typer.Option(
        "markdown", "--format", help="Report output format. Only 'markdown' is supported."
    ),
) -> None:
    """Render a case's full investigative content as a single, deterministic Markdown document.

    Writes to stdout by default; pass --output to write the same
    deterministic bytes to a file instead.
    """
    if output_format != "markdown":
        raise typer.BadParameter(
            f"unsupported --format {output_format!r}; only 'markdown' is supported"
        )
    if output is not None and output.exists():
        typer.echo(f"error: {output} already exists", err=True)
        raise typer.Exit(1)

    try:
        case = Case.open(case_dir)
    except sqlite3.DatabaseError:
        _fail_corrupted_case(case_dir)

    try:
        try:
            report_bytes = render_report_bytes(
                case_name=case_dir.name,
                store=case.store,
                recomputed_manifest=case.compute_manifest(),
                recorded_manifest=case.load_recorded_manifest(),
            )
        except sqlite3.DatabaseError:
            _fail_corrupted_case(case_dir)
    finally:
        case.close()

    if output is None:
        sys.stdout.buffer.write(report_bytes)
        sys.stdout.buffer.flush()
    else:
        output.write_bytes(report_bytes)
        typer.echo(f"wrote report to {output}")


@app.command()
def verify(
    case_dir: Path = typer.Argument(..., help="Case directory to verify."),
    check_report: bool = typer.Option(
        False, "--report", help="Also confirm the report regenerates without error."
    ),
) -> None:
    """Confirm a case's integrity and reproducibility: recompute its manifest
    and compare it to the recorded one (as `replay` does), and optionally
    confirm the report still regenerates without error.
    """
    try:
        case = Case.open(case_dir)
    except sqlite3.DatabaseError:
        _fail_corrupted_case(case_dir)

    report_failed = False
    try:
        try:
            result = replay_and_verify(case)
        except sqlite3.DatabaseError:
            _fail_corrupted_case(case_dir)

        typer.echo(f"recomputed manifest hash: {result.recomputed_manifest.manifest_hash}")
        if result.recorded_manifest is not None:
            typer.echo(f"recorded manifest hash:   {result.recorded_manifest.manifest_hash}")
        typer.echo(_replay_verdict(result))

        if check_report:
            try:
                render_report_bytes(
                    case_name=case_dir.name,
                    store=case.store,
                    recomputed_manifest=result.recomputed_manifest,
                    recorded_manifest=result.recorded_manifest,
                )
            except sqlite3.DatabaseError:
                _fail_corrupted_case(case_dir)
            except Exception as exc:  # noqa: BLE001 -- smoke check must surface any failure
                report_failed = True
                typer.echo(f"report generation: FAILED: {exc}", err=True)
            else:
                typer.echo("report generation: OK")
    finally:
        case.close()

    if not result.matches_recorded or report_failed:
        raise typer.Exit(1)


@app.command()
def contradictions(case_dir: Path) -> None:
    """Report structural TimeAssertion contradictions found in a case."""
    case = Case.open(case_dir)
    found = detect_time_contradictions(case.store)
    case.close()
    if not found:
        typer.echo("no contradictions found")
        return
    for c in found:
        typer.echo(
            f"event {c.subject_event_id}: "
            f"{c.assertion_a.value.isoformat()} ({c.assertion_a.source_evidence_id}) vs "
            f"{c.assertion_b.value.isoformat()} ({c.assertion_b.source_evidence_id})"
        )


@app.command()
def replay(case_dir: Path) -> None:
    """Recompute a case's provenance manifest and verify it against the recorded one."""
    try:
        case = Case.open(case_dir)
    except sqlite3.DatabaseError:
        _fail_corrupted_case(case_dir)
    try:
        try:
            result = replay_and_verify(case)
        except sqlite3.DatabaseError:
            _fail_corrupted_case(case_dir)
    finally:
        case.close()
    typer.echo(f"recomputed manifest hash: {result.recomputed_manifest.manifest_hash}")
    if result.recorded_manifest is not None:
        typer.echo(f"recorded manifest hash:   {result.recorded_manifest.manifest_hash}")
    typer.echo(_replay_verdict(result))
    if not result.matches_recorded:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

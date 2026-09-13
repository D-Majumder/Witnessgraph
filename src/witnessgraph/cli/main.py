"""Witnessgraph CLI entry point."""

from __future__ import annotations

import sqlite3
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import typer

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import validate_source_id
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis, HypothesisStatus
from witnessgraph.core.ids import canonical_json_bytes
from witnessgraph.core.relationships import Relationship
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.core.tracked_finding import FindingStatus, TrackedGapFinding
from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction
from witnessgraph.correlate.contradiction_tracking import track_contradictions
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.correlate.gaps import DEFAULT_MIN_CORROBORATING_EVENTS, find_gaps
from witnessgraph.correlate.graph import (
    DEFAULT_NEIGHBORS_MAX_DEPTH,
    DEFAULT_PATH_MAX_DEPTH,
    MAX_ALLOWED_DEPTH,
    GraphDirection,
    ResolvedEntity,
    TraversalStep,
    components_result_to_json,
    explain_relationship,
    find_components,
    find_neighbors,
    find_path,
    neighbors_result_to_json,
    path_result_to_json,
    resolve_entity,
)
from witnessgraph.correlate.tracking import is_still_reproduced, track_findings
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.ingest.registry import get_adapter, list_adapters
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import ReplayResult, replay_and_verify
from witnessgraph.report.render import render_report_bytes
from witnessgraph.report.render_json import render_report_json_bytes
from witnessgraph.store.base import Store
from witnessgraph.store.case import Case

app = typer.Typer(
    help="Witnessgraph: an evidence-first, reproducible cybersecurity investigation platform.",
    no_args_is_help=True,
)
entities_app = typer.Typer(help="Inspect and create entities in a case.", no_args_is_help=True)
relationships_app = typer.Typer(
    help=(
        "Create and inspect evidence-backed relationships between entities "
        "(v1.1) -- the graph's edges. Directed: a relationship's source "
        "and target entity are never inferred as also implying the reverse."
    ),
    no_args_is_help=True,
)
graph_app = typer.Typer(
    help=(
        "Traverse the graph of Relationships between Entities (v1.1). "
        "Structural analysis only -- a result describes what is connected "
        "to what, and through which cited evidence, never a claim of "
        "causation, responsibility, or truth."
    ),
    no_args_is_help=True,
)
hypothesis_app = typer.Typer(help="Manage hypotheses in a case.", no_args_is_help=True)
findings_app = typer.Typer(
    help="Inspect and annotate persisted, tracked gap-analysis findings (v0.7).",
    no_args_is_help=True,
)
contradiction_findings_app = typer.Typer(
    help=(
        "Inspect and annotate persisted, tracked time-contradiction findings "
        "(v0.8). Structurally separate from `findings` -- a contradiction id "
        "is never looked up in the gap-finding table, and vice versa."
    ),
    no_args_is_help=True,
)
time_assertions_app = typer.Typer(
    help=(
        "Record explicit, analyst-declared TimeAssertion claims in a case "
        "(v1.0). A TimeAssertion created here is one named analyst's claim, "
        "grounded in cited evidence, about when a NormalizedEvent occurred -- "
        "never an adjudicated fact. Witnessgraph does not resolve disagreeing "
        "claims about the same event into one true timestamp; see "
        "`witnessgraph contradiction-findings`."
    ),
    no_args_is_help=True,
)
app.add_typer(entities_app, name="entities")
app.add_typer(relationships_app, name="relationships")
app.add_typer(graph_app, name="graph")
app.add_typer(hypothesis_app, name="hypothesis")
app.add_typer(findings_app, name="findings")
app.add_typer(contradiction_findings_app, name="contradiction-findings")
app.add_typer(time_assertions_app, name="time-assertions")


def _resolve_evidence_ref(case: Case, ref_id: str) -> EvidenceRef:
    if case.store.get_evidence(ref_id) is not None:
        return EvidenceRef(kind="evidence_item", id=ref_id)
    if case.store.get_normalized_event(ref_id) is not None:
        return EvidenceRef(kind="normalized_event", id=ref_id)
    raise typer.BadParameter(f"{ref_id!r} is not a known EvidenceItem or NormalizedEvent id")


def _format_resolved_source_plain(source: str, refinement: str | None) -> str:
    """Render a resolved gap-analysis source for plain CLI text (v0.6).

    ``refinement`` is already neutralized by ``find_gaps`` before this is
    called, so no further escaping is needed for plain terminal output --
    see ``correlate.gaps._neutralize_for_grouping``.
    """
    if refinement is None:
        return source
    return f"{source} (refined: {refinement})"


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


def _open_case_or_fail(case_dir: Path) -> Case:
    """Open a case, turning the missing-directory/unreadable-database
    exceptions ``Case.open`` raises into the same clean, single-line
    failure every command should present instead of a raw traceback."""
    try:
        return Case.open(case_dir)
    except FileNotFoundError:
        typer.echo(
            f"error: {case_dir} does not look like a Witnessgraph case (no case.db)", err=True
        )
        raise typer.Exit(1) from None
    except sqlite3.DatabaseError:
        _fail_corrupted_case(case_dir)


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
    case = _open_case_or_fail(case_dir)
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
    case = _open_case_or_fail(case_dir)
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
    case = _open_case_or_fail(case_dir)
    for entity in case.store.list_entities():
        typer.echo(f"{entity.id}  {entity.entity_type}  {entity.identifiers}")
    case.close()


@entities_app.command("show")
def entities_show(case_dir: Path, entity_id: str) -> None:
    case = _open_case_or_fail(case_dir)
    entity = case.store.get_entity(entity_id)
    case.close()
    if entity is None:
        typer.echo(f"no such entity: {entity_id}", err=True)
        raise typer.Exit(1)
    typer.echo(entity.model_dump_json(indent=2))


@relationships_app.command("create")
def relationships_create(
    case_dir: Path = typer.Argument(..., help="Case directory to modify."),
    relationship_type: str = typer.Argument(
        ..., help="Free-form label for the relationship, e.g. 'connected_to'."
    ),
    source: str = typer.Option(..., "--source", help="Source entity id (edge start)."),
    target: str = typer.Option(..., "--target", help="Target entity id (edge end)."),
    derived_from: list[str] = typer.Option(
        ...,
        "--derived-from",
        help="EvidenceItem or NormalizedEvent id this relationship is grounded in.",
    ),
    attribute: list[str] = typer.Option(
        [], "--attribute", help="key=value attribute, e.g. --attribute protocol=tcp"
    ),
) -> None:
    """Create a directed, evidence-backed relationship between two existing entities.

    Witnessgraph never infers a relationship on its own -- this always
    records an explicit analyst claim, grounded in cited evidence, that
    ``source`` and ``target`` were observed to be connected. Re-running
    this command with identical arguments is a safe, idempotent no-op:
    like `time-assertions create`, a Relationship's id is content-derived,
    so it converges rather than duplicates.
    """
    case = _open_case_or_fail(case_dir)
    if case.store.get_entity(source) is None:
        case.close()
        raise typer.BadParameter(f"{source!r} is not a known Entity id", param_hint="--source")
    if case.store.get_entity(target) is None:
        case.close()
        raise typer.BadParameter(f"{target!r} is not a known Entity id", param_hint="--target")
    for ref_id in derived_from:
        is_evidence = case.store.get_evidence(ref_id) is not None
        is_event = case.store.get_normalized_event(ref_id) is not None
        if not (is_evidence or is_event):
            case.close()
            raise typer.BadParameter(
                f"{ref_id!r} is not a known EvidenceItem/NormalizedEvent id",
                param_hint="--derived-from",
            )
    try:
        attributes = dict(pair.split("=", 1) for pair in attribute)
    except ValueError:
        case.close()
        raise typer.BadParameter(
            "must be in key=value form", param_hint="--attribute"
        ) from None
    try:
        relationship = Relationship.create(
            relationship_type=relationship_type,
            source_entity_id=source,
            target_entity_id=target,
            derived_from=tuple(derived_from),
            created_at=datetime.now(UTC),
            attributes=attributes,
        )
    except ValueError as exc:
        case.close()
        raise typer.BadParameter(str(exc)) from exc
    already_existed = case.store.get_relationship(relationship.id) is not None
    case.store.put_relationship(relationship)
    case.record_manifest()
    case.close()
    if already_existed:
        typer.echo(f"relationship {relationship.id} already exists -- unchanged")
    else:
        typer.echo(
            f"created relationship {relationship.id}: "
            f"{source} -[{relationship_type}]-> {target}"
        )


@relationships_app.command("list")
def relationships_list(
    case_dir: Path = typer.Argument(..., help="Case directory to inspect."),
    entity: str | None = typer.Option(
        None,
        "--entity",
        help="Only show relationships where this entity id is the source or target.",
    ),
) -> None:
    """List relationships in a case, optionally filtered to one entity."""
    case = _open_case_or_fail(case_dir)
    relationships = case.store.list_relationships()
    case.close()
    if entity is not None:
        relationships = [
            r for r in relationships if entity in (r.source_entity_id, r.target_entity_id)
        ]
    if not relationships:
        typer.echo("no relationships")
        return
    for rel in relationships:
        typer.echo(
            f"{rel.id}  {rel.source_entity_id} -[{rel.relationship_type}]-> "
            f"{rel.target_entity_id}"
        )


@relationships_app.command("show")
def relationships_show(case_dir: Path, relationship_id: str) -> None:
    case = _open_case_or_fail(case_dir)
    relationship = case.store.get_relationship(relationship_id)
    case.close()
    if relationship is None:
        typer.echo(f"no such relationship: {relationship_id}", err=True)
        raise typer.Exit(1)
    typer.echo(relationship.model_dump_json(indent=2))


@time_assertions_app.command("create")
def time_assertions_create(
    case_dir: Path = typer.Argument(..., help="Case directory to modify."),
    event_id: str = typer.Argument(..., help="NormalizedEvent id this claim is about."),
    value: str = typer.Option(
        ...,
        "--value",
        help=(
            "Timezone-aware ISO-8601 timestamp this claim asserts for the "
            "event. A naive (no offset/zone) timestamp is rejected rather "
            "than assumed to be in some particular timezone."
        ),
    ),
    precision: TimePrecision = typer.Option(
        ...,
        "--precision",
        help="Precision of the claimed value: exact, second, minute, hour, day, or approximate.",
    ),
    source_evidence: str = typer.Option(
        ...,
        "--source-evidence",
        help=(
            "Required: id of the EvidenceItem this claim is grounded in. "
            "Only checked for existence -- it is not required to be among "
            "the subject event's own derived_from evidence, since a claim "
            "may legitimately be grounded in evidence external to the "
            "event it is about."
        ),
    ),
    by: str = typer.Option(
        ...,
        "--by",
        help=(
            "Required: the analyst identity making this claim. There is no "
            "default -- an analyst identity is never invented or inferred "
            "by this tool. Must not be blank or whitespace-only. This tool "
            "never adjudicates whose claim is correct; it only records who "
            "is making it and what evidence it is grounded in."
        ),
    ),
) -> None:
    """Record one analyst's explicit claim about when a NormalizedEvent occurred.

    This creates a TimeAssertion: a specific person's claim, grounded in
    cited evidence, about an event's time -- not an adjudicated fact.
    Multiple, even disagreeing, claims about the same event are preserved
    side by side (see `witnessgraph contradiction-findings`); this command
    never resolves or overwrites an existing claim, and re-running it with
    identical arguments is a safe, idempotent no-op.
    """
    if not by.strip():
        raise typer.BadParameter(
            "must not be blank or whitespace-only -- an analyst identity is "
            "never invented or inferred by this tool",
            param_hint="--by",
        )
    try:
        parsed_value = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{value!r} is not a valid ISO-8601 timestamp", param_hint="--value"
        ) from exc
    if parsed_value.tzinfo is None:
        raise typer.BadParameter(
            "must be timezone-aware -- an ambiguous (naive) timestamp is "
            "never assumed to be in some particular timezone",
            param_hint="--value",
        )

    case = _open_case_or_fail(case_dir)
    if case.store.get_normalized_event(event_id) is None:
        case.close()
        raise typer.BadParameter(
            f"{event_id!r} is not a known NormalizedEvent id", param_hint="event_id"
        )
    if case.store.get_evidence(source_evidence) is None:
        case.close()
        raise typer.BadParameter(
            f"{source_evidence!r} is not a known EvidenceItem id",
            param_hint="--source-evidence",
        )

    assertion = TimeAssertion.create(
        subject_event_id=event_id,
        value=parsed_value,
        precision=precision,
        source_evidence_id=source_evidence,
        asserted_by=by,
        created_at=datetime.now(UTC),
    )
    already_existed = case.store.get_time_assertion(assertion.id) is not None
    case.store.put_time_assertion(assertion)
    case.record_manifest()
    case.close()

    if already_existed:
        typer.echo(
            f"time assertion {assertion.id} already exists -- unchanged: "
            f"a claim by analyst {by!r} that event {event_id} occurred at "
            f"{parsed_value.isoformat()} ({precision.value} precision), "
            f"grounded in evidence {source_evidence}"
        )
    else:
        typer.echo(
            f"created time assertion {assertion.id}: a claim by analyst "
            f"{by!r} that event {event_id} occurred at "
            f"{parsed_value.isoformat()} ({precision.value} precision) -- "
            f"this event's coverage is attributed to evidence "
            f"{source_evidence} via analyst {by!r}"
        )


@app.command()
def timeline(case_dir: Path) -> None:
    """Print all normalized events, ordered by their earliest known time assertion."""
    case = _open_case_or_fail(case_dir)
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
    case = _open_case_or_fail(case_dir)
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
    case = _open_case_or_fail(case_dir)
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
    case = _open_case_or_fail(case_dir)
    for hyp in case.store.list_hypotheses():
        typer.echo(f"{hyp.id}  [{hyp.status.value}]  {hyp.statement}")
    case.close()


@app.command()
def export(
    case_dir: Path,
    output: Path = typer.Argument(..., help="Output .wgcase archive path."),
) -> None:
    """Package a case directory into a single portable .wgcase archive."""
    case = _open_case_or_fail(case_dir)
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
    except FileNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    except FileExistsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    except zipfile.BadZipFile:
        typer.echo(f"error: {archive} is not a valid .wgcase archive (not a zip file)", err=True)
        raise typer.Exit(1) from None
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
        "markdown",
        "--format",
        help=(
            "Report output format: 'markdown' (default, human-readable) or "
            "'json' (v0.9, machine-readable -- see `witnessgraph report "
            "--format json`'s output for the schema; JSON output is NOT "
            "passed through the same display-safety neutralization "
            "Markdown output is -- see report.render_json's module "
            "docstring)."
        ),
    ),
) -> None:
    """Render a case's full investigative content as a single, deterministic
    Markdown (default) or JSON document.

    Writes to stdout by default; pass --output to write the same
    deterministic bytes to a file instead -- stdout and --output always
    contain byte-identical content for a given format.
    """
    if output_format not in ("markdown", "json"):
        raise typer.BadParameter(
            f"unsupported --format {output_format!r}; only 'markdown' or 'json' is supported"
        )
    if output is not None and output.exists():
        typer.echo(f"error: {output} already exists", err=True)
        raise typer.Exit(1)

    case = _open_case_or_fail(case_dir)

    try:
        try:
            if output_format == "json":
                report_bytes = render_report_json_bytes(
                    case_name=case_dir.name,
                    store=case.store,
                    recomputed_manifest=case.compute_manifest(),
                    recorded_manifest=case.load_recorded_manifest(),
                )
            else:
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
    case = _open_case_or_fail(case_dir)

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
def contradictions(
    case_dir: Path = typer.Argument(..., help="Case directory to analyze."),
    track: bool = typer.Option(
        False,
        "--track",
        help=(
            "Optional (v0.8): after reporting, persist each contradiction "
            "found above as a tracked contradiction (see "
            "`witnessgraph contradiction-findings`). Mechanical discovery "
            "only -- no analyst identity is accepted or required here; a "
            "freshly tracked contradiction starts unannotated (status "
            "'open'). A contradiction already tracked from a prior run is "
            "left completely unchanged, including any existing annotation. "
            "Omitting this flag reproduces pre-v0.8 behavior exactly: "
            "nothing is persisted."
        ),
    ),
) -> None:
    """Report structural TimeAssertion contradictions found in a case."""
    case = _open_case_or_fail(case_dir)
    # The full, read-only detection always completes before any
    # persistence is attempted -- see track_contradictions's docstring.
    found = detect_time_contradictions(case.store)
    if not found:
        typer.echo("no contradictions found")
    for c in found:
        typer.echo(
            f"event {c.subject_event_id}: "
            f"{c.assertion_a.value.isoformat()} ({c.assertion_a.source_evidence_id}) vs "
            f"{c.assertion_b.value.isoformat()} ({c.assertion_b.source_evidence_id})"
        )
    if track:
        # Persistence only, after the complete read-only detection above --
        # one transaction covers every new row this invocation creates.
        with case.transaction():
            outcomes = track_contradictions(case.store, found)
        new_count = sum(1 for o in outcomes if o.newly_created)
        already_tracked = len(outcomes) - new_count
        typer.echo(
            f"tracked: {new_count} new contradiction(s), {already_tracked} already tracked"
        )
    case.close()


@app.command()
def gaps(
    case_dir: Path = typer.Argument(..., help="Case directory to analyze."),
    min_gap_seconds: float = typer.Option(
        ...,
        "--min-gap-seconds",
        help=(
            "Minimum gap duration (seconds) to report. Required -- no default is "
            "claimed to be objectively correct; choose per case. See "
            "docs/phase5-v0.5-gap-analysis-design.md §7/§23."
        ),
    ),
    min_corroborating_events: int = typer.Option(
        DEFAULT_MIN_CORROBORATING_EVENTS,
        "--min-corroborating-events",
        help="Minimum corroborating events required from the present source.",
    ),
    refine_source_by_attribute: str | None = typer.Option(
        None,
        "--refine-source-by-attribute",
        help=(
            "Optional (v0.6): subdivide each declared source by this "
            "NormalizedEvent attribute (e.g. 'host'). Never overrides or "
            "invents a coarse source; a record missing the attribute falls "
            "back to its coarse source. The value comes from ingested, "
            "untrusted content and does NOT prove physical source identity. "
            "Omitting this reproduces v0.5 behavior exactly."
        ),
    ),
    track: bool = typer.Option(
        False,
        "--track",
        help=(
            "Optional (v0.7): after reporting, persist each finding found "
            "above as a tracked finding (see `witnessgraph findings`). "
            "Mechanical discovery only -- no analyst identity is accepted "
            "or required here; a freshly tracked finding starts unannotated "
            "(status 'open'). A finding already tracked from a prior run is "
            "left completely unchanged, including any existing annotation. "
            "Omitting this flag reproduces pre-v0.7 behavior exactly: "
            "nothing is persisted."
        ),
    ),
) -> None:
    """Report deterministic cross-source evidence coverage gaps.

    A finding means: the given source has no observed evidence in the
    stated interval while a different, independently-declared source has
    corroborating activity there. This is never a claim that an event
    should have existed -- see docs/phase5-v0.5-gap-analysis-design.md.
    Source identity is resolved only from explicitly declared
    ``--source-id`` values (``witnessgraph ingest --source-id``); evidence
    with no or an ambiguous declared source is excluded, not guessed.
    """
    if min_corroborating_events < 1:
        raise typer.BadParameter(
            "must be at least 1 -- a gap can never be reported on zero corroborating "
            "evidence (see docs/phase5-v0.5-gap-analysis-design.md §7/§23)",
            param_hint="--min-corroborating-events",
        )
    case = _open_case_or_fail(case_dir)
    # The full, read-only analysis always completes before any persistence
    # is attempted -- see track_findings's docstring and the design's
    # transaction-boundary requirement.
    result = find_gaps(
        case.store,
        min_gap_seconds=min_gap_seconds,
        min_corroborating_events=min_corroborating_events,
        refine_source_by_attribute=refine_source_by_attribute,
    )
    if result.refine_source_by_attribute is not None:
        typer.echo(
            f"source identity refined by attribute `{result.refine_source_by_attribute}` "
            "-- this does not prove physical source identity"
        )
    if not result.findings:
        typer.echo("no coverage gaps found")
    for f in result.findings:
        absent_label = _format_resolved_source_plain(f.absent_source, f.absent_source_refinement)
        present_label = _format_resolved_source_plain(
            f.present_source, f.present_source_refinement
        )
        typer.echo(
            f"source `{absent_label}` has no observed evidence in "
            f"[{f.interval_start.isoformat()}, {f.interval_end.isoformat()}) "
            f"while source `{present_label}` has corroborating activity "
            f"(bounded by time assertions {f.bounding_absent_assertion_ids[0]}.."
            f"{f.bounding_absent_assertion_ids[1]}; corroborated by "
            f"{len(f.corroborating_time_assertion_ids)} assertion(s): "
            f"{', '.join(f.corroborating_time_assertion_ids)})"
        )
    excluded_summary = (
        f"excluded: {result.excluded_no_time_assertion} normalized event(s) with no time "
        f"assertion, {result.excluded_no_declared_source} time assertion(s) with no "
        f"declared source, {result.excluded_ambiguous_source} time assertion(s) with "
        "ambiguous declared source"
    )
    if result.refine_source_by_attribute is not None:
        excluded_summary += (
            f", {result.excluded_unrefined_fallback_with_refined_sibling} time assertion(s) "
            "in an unrefined fallback bucket excluded from comparison against a refined "
            "sibling group of the same coarse source (still comparable against genuinely "
            "different coarse sources)"
        )
    typer.echo(excluded_summary)

    if track:
        # Persistence only, after the complete read-only analysis above --
        # one transaction covers every new row this invocation creates.
        with case.transaction():
            outcomes = track_findings(
                case.store,
                result,
                min_gap_seconds=min_gap_seconds,
                min_corroborating_events=min_corroborating_events,
            )
        new_count = sum(1 for o in outcomes if o.newly_created)
        already_tracked = len(outcomes) - new_count
        typer.echo(f"tracked: {new_count} new finding(s), {already_tracked} already tracked")
    case.close()


def _format_step_text(step: TraversalStep) -> str:
    rel = step.relationship
    derived = ", ".join(f"`{d}`" for d in rel.derived_from)
    return (
        f"{step.from_entity_id} --[{rel.relationship_type} via `{rel.id}`, "
        f"{step.walked_direction}]--> {step.to_entity_id} (derived_from: {derived})"
    )


def _validate_graph_format(output_format: str) -> None:
    if output_format not in ("text", "json"):
        raise typer.BadParameter(
            f"unsupported --format {output_format!r}; only 'text' or 'json' is supported"
        )


_EXPLAIN_HELP = (
    "Additionally resolve every relationship's derived_from ids and every "
    "participating entity id to their stored records (evidence source/"
    "locator, entity type/identifiers) -- a structural provenance "
    "expansion of what is already in this result, never a new traversal "
    "and never a forensic conclusion. Must be run while the case is open, "
    "so it has no effect on --max-depth/--min-size bounds."
)


def _format_evidence_lineage_text(store: Store, rel: Relationship, indent: str) -> list[str]:
    lines = [f"{indent}evidence:"]
    for ref in explain_relationship(store, rel):
        if ref.kind == "evidence_item" and ref.evidence_item is not None:
            item = ref.evidence_item
            lines.append(
                f"{indent}  - evidence_item `{item.id}`: source_adapter={item.source_adapter}, "
                f"source_locator={item.source_locator}, "
                f"collected_at={item.collected_at.isoformat()}"
            )
        elif ref.kind == "normalized_event" and ref.normalized_event is not None:
            event = ref.normalized_event
            lines.append(
                f"{indent}  - normalized_event `{event.id}`: event_type={event.event_type}"
            )
        else:
            lines.append(f"{indent}  - `{ref.id}`: not found in this case")
    return lines


def _format_resolved_entity_text(resolved: ResolvedEntity) -> str:
    if resolved.entity is None:
        return f"  - `{resolved.entity_id}`: not found in this case"
    identifiers = ", ".join(f"{k}={v}" for k, v in sorted(resolved.entity.identifiers.items()))
    return (
        f"  - `{resolved.entity_id}` ({resolved.entity.entity_type}): "
        f"{identifiers or '(no identifiers)'}"
    )


def _format_entities_text(store: Store, entity_ids: set[str]) -> list[str]:
    lines = ["entities:"]
    for entity_id in sorted(entity_ids):
        lines.append(_format_resolved_entity_text(resolve_entity(store, entity_id)))
    return lines


@graph_app.command("neighbors")
def graph_neighbors(
    case_dir: Path = typer.Argument(..., help="Case directory to inspect."),
    entity_id: str = typer.Argument(..., help="Entity id to find neighbors of."),
    max_depth: int = typer.Option(
        DEFAULT_NEIGHBORS_MAX_DEPTH,
        "--max-depth",
        help=(
            f"Maximum number of hops to traverse (1-{MAX_ALLOWED_DEPTH}). "
            "1 (the default) means direct neighbors only."
        ),
    ),
    direction: GraphDirection = typer.Option(
        GraphDirection.OUT.value,
        "--direction",
        help=(
            "Which edges to follow: 'out' (default -- only this entity's "
            "own outgoing relationships), 'in' (only incoming), or 'both'. "
            "Relationships are directed; 'out' never treats an incoming "
            "edge as if it pointed the other way."
        ),
    ),
    explain: bool = typer.Option(False, "--explain", help=_EXPLAIN_HELP),
    output_format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """List every entity reachable from ENTITY_ID within --max-depth hops.

    A structural result only: an entity appearing here was found via a
    chain of explicit, evidence-backed Relationships -- never a claim
    that the entities are meaningfully associated beyond what those
    relationships and their cited evidence actually establish.
    """
    _validate_graph_format(output_format)
    if not (1 <= max_depth <= MAX_ALLOWED_DEPTH):
        raise typer.BadParameter(
            f"must be between 1 and {MAX_ALLOWED_DEPTH}", param_hint="--max-depth"
        )
    case = _open_case_or_fail(case_dir)
    if case.store.get_entity(entity_id) is None:
        case.close()
        typer.echo(f"no such entity: {entity_id}", err=True)
        raise typer.Exit(1)
    result = find_neighbors(case.store, entity_id, max_depth=max_depth, direction=direction)

    if output_format == "json":
        doc = neighbors_result_to_json(result, store=case.store if explain else None)
        case.close()
        sys.stdout.buffer.write(canonical_json_bytes(doc))
        sys.stdout.buffer.flush()
        return

    if not result.reached:
        case.close()
        typer.echo(
            f"no entities reached from {entity_id} within {max_depth} hop(s) "
            f"(direction={direction.value})"
        )
        return
    lines = [
        f"neighbors of {entity_id} (direction={direction.value}, max-depth={max_depth}): "
        f"{len(result.reached)} entity(ies) reached"
    ]
    for reached in result.reached:
        lines.append(f"- hop {reached.hop_count}: {_format_step_text(reached.via)}")
        if explain:
            lines.extend(
                _format_evidence_lineage_text(case.store, reached.via.relationship, "   ")
            )
    if explain:
        entity_ids = {entity_id} | {r.entity_id for r in result.reached}
        lines.extend(_format_entities_text(case.store, entity_ids))
    case.close()
    for line in lines:
        typer.echo(line)


@graph_app.command("path")
def graph_path(
    case_dir: Path = typer.Argument(..., help="Case directory to inspect."),
    source_entity_id: str = typer.Argument(..., help="Entity id to search from."),
    target_entity_id: str = typer.Argument(..., help="Entity id to search for."),
    max_depth: int = typer.Option(
        DEFAULT_PATH_MAX_DEPTH,
        "--max-depth",
        help=f"Maximum number of hops to search before giving up (1-{MAX_ALLOWED_DEPTH}).",
    ),
    direction: GraphDirection = typer.Option(
        GraphDirection.OUT.value,
        "--direction",
        help=(
            "Which edges to follow: 'out' (default -- only forward along "
            "each relationship's own direction), 'in' (only backward), or "
            "'both' (either way -- an explicit, undirected search)."
        ),
    ),
    explain: bool = typer.Option(False, "--explain", help=_EXPLAIN_HELP),
    output_format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Find one deterministic, shortest relationship chain from SOURCE_ENTITY_ID
    to TARGET_ENTITY_ID, within --max-depth hops.

    Reports a structural connection only, with full step-by-step
    provenance (each step's relationship id, type, and cited evidence) --
    never a claim of causation, responsibility, or truth. If more than
    one shortest chain exists, the one reported is chosen by a fixed,
    documented, deterministic rule (breadth-first search breaking ties by
    relationship id -- see correlate.graph's module docstring), never by
    incidental storage order. "No path found" within the searched depth
    is a valid result, not an error.
    """
    _validate_graph_format(output_format)
    if not (1 <= max_depth <= MAX_ALLOWED_DEPTH):
        raise typer.BadParameter(
            f"must be between 1 and {MAX_ALLOWED_DEPTH}", param_hint="--max-depth"
        )
    case = _open_case_or_fail(case_dir)
    if case.store.get_entity(source_entity_id) is None:
        case.close()
        typer.echo(f"no such entity: {source_entity_id}", err=True)
        raise typer.Exit(1)
    if case.store.get_entity(target_entity_id) is None:
        case.close()
        typer.echo(f"no such entity: {target_entity_id}", err=True)
        raise typer.Exit(1)
    result = find_path(
        case.store, source_entity_id, target_entity_id, max_depth=max_depth, direction=direction
    )

    if output_format == "json":
        doc = path_result_to_json(result, store=case.store if explain else None)
        case.close()
        sys.stdout.buffer.write(canonical_json_bytes(doc))
        sys.stdout.buffer.flush()
        return

    if not result.found:
        case.close()
        typer.echo(
            f"no path found from {source_entity_id} to {target_entity_id} "
            f"within {max_depth} hop(s) (direction={direction.value})"
        )
        return
    if source_entity_id == target_entity_id:
        case.close()
        typer.echo(f"{source_entity_id} is the search target itself: 0 hop(s)")
        return
    lines = [f"path found: {result.hop_count} hop(s)"]
    for i, step in enumerate(result.steps, start=1):
        lines.append(f"step {i}: {_format_step_text(step)}")
        if explain:
            lines.extend(_format_evidence_lineage_text(case.store, step.relationship, "   "))
    if explain:
        entity_ids = {source_entity_id, target_entity_id}
        for step in result.steps:
            entity_ids.add(step.from_entity_id)
            entity_ids.add(step.to_entity_id)
        lines.extend(_format_entities_text(case.store, entity_ids))
    case.close()
    for line in lines:
        typer.echo(line)


def _format_relationship_text(rel: Relationship) -> str:
    derived = ", ".join(f"`{d}`" for d in rel.derived_from)
    return (
        f"`{rel.id}`: {rel.source_entity_id} -[{rel.relationship_type}]-> "
        f"{rel.target_entity_id} (derived_from: {derived})"
    )


@graph_app.command("components")
def graph_components(
    case_dir: Path = typer.Argument(..., help="Case directory to inspect."),
    min_size: int = typer.Option(
        1,
        "--min-size",
        help=(
            "Only show components with at least this many entities "
            "(default 1: show everything). Every component has at least "
            "2 entities by construction -- an entity is only ever part of "
            "a component because it appears in a relationship with "
            "another entity -- so --min-size 1 and --min-size 2 show the "
            "same result; the option exists to filter out small "
            "components in a large, heavily-clustered case."
        ),
    ),
    explain: bool = typer.Option(False, "--explain", help=_EXPLAIN_HELP),
    output_format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Partition every entity that appears in a Relationship into
    weakly-connected clusters (components) -- entities joined, directly
    or through a chain of relationships, treating direction as
    irrelevant (unlike `graph neighbors`/`graph path`, which are directed
    by default -- see correlate.graph's module docstring for why cluster
    membership is a genuinely different question from point-to-point
    reachability).

    A structural partition only, with full relationship/evidence
    provenance for every edge -- never a claim that everything in one
    component shares a cause, an actor, or a conclusion. An entity with
    no relationships at all is not part of any component.
    """
    _validate_graph_format(output_format)
    if min_size < 1:
        raise typer.BadParameter("must be at least 1", param_hint="--min-size")
    case = _open_case_or_fail(case_dir)
    result = find_components(case.store, min_size=min_size)

    if output_format == "json":
        doc = components_result_to_json(result, store=case.store if explain else None)
        case.close()
        sys.stdout.buffer.write(canonical_json_bytes(doc))
        sys.stdout.buffer.flush()
        return

    if result.total_entities_in_graph == 0:
        case.close()
        typer.echo("no relationships in this case -- nothing to partition into components")
        return
    if not result.components:
        case.close()
        typer.echo(
            f"no components with at least {min_size} entity(ies) -- "
            f"{result.total_components_found} component(s) exist in this "
            f"case, none meet that threshold"
        )
        return
    lines = [
        f"{len(result.components)} component(s) covering "
        f"{sum(len(c.entity_ids) for c in result.components)} of "
        f"{result.total_entities_in_graph} entities in the relationship "
        f"graph ({result.total_relationships} relationship(s) total; "
        f"min-size={min_size})"
    ]
    for component in result.components:
        lines.append(
            f"- component {component.index}: {len(component.entity_ids)} entities, "
            f"{len(component.relationships)} relationship(s)"
        )
        entities = ", ".join(f"`{eid}`" for eid in component.entity_ids)
        lines.append(f"  entities: {entities}")
        for rel in component.relationships:
            lines.append(f"  - {_format_relationship_text(rel)}")
            if explain:
                lines.extend(_format_evidence_lineage_text(case.store, rel, "     "))
        if explain:
            component_entity_ids = set(component.entity_ids)
            lines.extend(
                f"  {entity_line}"
                for entity_line in _format_entities_text(case.store, component_entity_ids)
            )
    case.close()
    for line in lines:
        typer.echo(line)


def _format_tracked_finding_summary(finding: TrackedGapFinding, still_reproduced: bool) -> str:
    absent_label = _format_resolved_source_plain(
        finding.absent_source, finding.absent_source_refinement
    )
    present_label = _format_resolved_source_plain(
        finding.present_source, finding.present_source_refinement
    )
    reviewed_by = (
        f"{finding.status.value} by `{finding.annotated_by}` at "
        f"{finding.annotated_at.isoformat() if finding.annotated_at else ''}"
        if finding.annotated_by is not None
        else "not yet reviewed"
    )
    reproduced_label = "yes" if still_reproduced else "no"
    return (
        f"{finding.id}  `{absent_label}` absent / `{present_label}` present  "
        f"[{finding.interval_start.isoformat()}, {finding.interval_end.isoformat()})  "
        f"status={finding.status.value} ({reviewed_by})  "
        f"still reproduced by current evidence: {reproduced_label}"
    )


@findings_app.command("list")
def findings_list(case_dir: Path = typer.Argument(..., help="Case directory to inspect.")) -> None:
    """List every tracked (persisted) gap-analysis finding.

    ``status`` reflects an analyst's review process only -- ``reviewed``
    never means the underlying finding has been validated, and no status
    here is ever a claim that an absent event should have existed. The
    "still reproduced" indicator is computed live against current
    evidence, using each finding's own originally recorded analysis
    parameters, and is never itself persisted.
    """
    case = _open_case_or_fail(case_dir)
    tracked = case.store.list_tracked_findings()
    if not tracked:
        typer.echo("no tracked findings")
        case.close()
        return
    for finding in tracked:
        still_reproduced = is_still_reproduced(case.store, finding)
        typer.echo(_format_tracked_finding_summary(finding, still_reproduced))
    case.close()


@findings_app.command("show")
def findings_show(
    case_dir: Path = typer.Argument(..., help="Case directory to inspect."),
    finding_id: str = typer.Argument(..., help="Tracked finding id, from `findings list`."),
) -> None:
    """Show the full detail of one tracked finding, including its live
    "still reproduced" state (see `findings list`'s help for what that
    means and does not mean)."""
    case = _open_case_or_fail(case_dir)
    finding = case.store.get_tracked_finding(finding_id)
    if finding is None:
        case.close()
        typer.echo(f"no such tracked finding: {finding_id}", err=True)
        raise typer.Exit(1)
    still_reproduced = is_still_reproduced(case.store, finding)
    case.close()
    typer.echo(finding.model_dump_json(indent=2))
    typer.echo(f"still reproduced by current evidence: {'yes' if still_reproduced else 'no'}")


@findings_app.command("ack")
def findings_ack(
    case_dir: Path = typer.Argument(..., help="Case directory to modify."),
    finding_id: str = typer.Argument(..., help="Tracked finding id, from `findings list`."),
    status: FindingStatus = typer.Option(
        ..., "--status", help="New review status: open, reviewed, or dismissed."
    ),
    by: str = typer.Option(
        ...,
        "--by",
        help=(
            "Required: the analyst identity performing this review. There "
            "is no default -- an analyst identity is never invented or "
            "inferred by this tool. Must not be blank or whitespace-only."
        ),
    ),
    note: str | None = typer.Option(
        None, "--note", help="Optional free-text note explaining this review decision."
    ),
) -> None:
    """Replace a tracked finding's current review annotation.

    This REPLACES the existing status/attribution/note; it does not
    create a history record. There is no history table anywhere in this
    feature -- the previous status, attribution, and note are permanently
    discarded, not archived, once this command runs. A ``reviewed``
    status never means the underlying finding has been validated, and no
    status is ever a claim that an absent event should have existed.
    """
    if not by.strip():
        raise typer.BadParameter(
            "must not be blank or whitespace-only -- an analyst identity is "
            "never invented or inferred by this tool",
            param_hint="--by",
        )
    case = _open_case_or_fail(case_dir)
    try:
        updated = case.store.annotate_tracked_finding(
            finding_id,
            status=status,
            annotated_by=by,
            annotated_at=datetime.now(UTC),
            note=note,
        )
    except ValueError:
        case.close()
        typer.echo(f"no such tracked finding: {finding_id}", err=True)
        raise typer.Exit(1) from None
    case.close()
    typer.echo(
        f"tracked finding {updated.id} -> {updated.status.value} (by {updated.annotated_by})"
    )


def _format_tracked_contradiction_summary(contradiction: TrackedTimeContradiction) -> str:
    first_id, second_id = contradiction.assertion_ids
    reviewed_by = (
        f"{contradiction.status.value} by `{contradiction.annotated_by}` at "
        f"{contradiction.annotated_at.isoformat() if contradiction.annotated_at else ''}"
        if contradiction.annotated_by is not None
        else "not yet reviewed"
    )
    return (
        f"{contradiction.id}  event `{contradiction.subject_event_id}`  "
        f"assertions `{first_id}`, `{second_id}`  "
        f"status={contradiction.status.value} ({reviewed_by})"
    )


@contradiction_findings_app.command("list")
def contradiction_findings_list(
    case_dir: Path = typer.Argument(..., help="Case directory to inspect."),
) -> None:
    """List every tracked (persisted) time-contradiction finding.

    ``status`` reflects an analyst's review process only -- ``reviewed``/
    ``dismissed`` never mean the contradiction has been resolved,
    adjudicated, or that either assertion is more correct. Witnessgraph
    does not determine which disagreeing assertion is true.
    """
    case = _open_case_or_fail(case_dir)
    tracked = case.store.list_tracked_contradictions()
    if not tracked:
        typer.echo("no tracked contradictions")
        case.close()
        return
    for contradiction in tracked:
        typer.echo(_format_tracked_contradiction_summary(contradiction))
    case.close()


@contradiction_findings_app.command("show")
def contradiction_findings_show(
    case_dir: Path = typer.Argument(..., help="Case directory to inspect."),
    contradiction_id: str = typer.Argument(
        ..., help="Tracked contradiction id, from `contradiction-findings list`."
    ),
) -> None:
    """Show the full detail of one tracked contradiction."""
    case = _open_case_or_fail(case_dir)
    contradiction = case.store.get_tracked_contradiction(contradiction_id)
    if contradiction is None:
        case.close()
        typer.echo(f"no such tracked contradiction: {contradiction_id}", err=True)
        raise typer.Exit(1)
    case.close()
    typer.echo(contradiction.model_dump_json(indent=2))


@contradiction_findings_app.command("ack")
def contradiction_findings_ack(
    case_dir: Path = typer.Argument(..., help="Case directory to modify."),
    contradiction_id: str = typer.Argument(
        ..., help="Tracked contradiction id, from `contradiction-findings list`."
    ),
    status: FindingStatus = typer.Option(
        ..., "--status", help="New review status: open, reviewed, or dismissed."
    ),
    by: str = typer.Option(
        ...,
        "--by",
        help=(
            "Required: the analyst identity performing this review. There "
            "is no default -- an analyst identity is never invented or "
            "inferred by this tool. Must not be blank or whitespace-only."
        ),
    ),
    note: str | None = typer.Option(
        None, "--note", help="Optional free-text note explaining this review decision."
    ),
) -> None:
    """Replace a tracked contradiction's current review annotation.

    This REPLACES the existing status/attribution/note; it does not
    create a history record. There is no history table anywhere in this
    feature -- the previous status, attribution, and note are permanently
    discarded, not archived, once this command runs. A ``reviewed``/
    ``dismissed`` status never means the contradiction has been resolved,
    adjudicated, or that either assertion is more correct -- Witnessgraph
    does not determine which disagreeing assertion is true.
    """
    if not by.strip():
        raise typer.BadParameter(
            "must not be blank or whitespace-only -- an analyst identity is "
            "never invented or inferred by this tool",
            param_hint="--by",
        )
    case = _open_case_or_fail(case_dir)
    try:
        updated = case.store.annotate_tracked_contradiction(
            contradiction_id,
            status=status,
            annotated_by=by,
            annotated_at=datetime.now(UTC),
            note=note,
        )
    except ValueError:
        case.close()
        typer.echo(f"no such tracked contradiction: {contradiction_id}", err=True)
        raise typer.Exit(1) from None
    case.close()
    typer.echo(
        f"tracked contradiction {updated.id} -> {updated.status.value} (by {updated.annotated_by})"
    )


@app.command()
def replay(case_dir: Path) -> None:
    """Recompute a case's provenance manifest and verify it against the recorded one."""
    case = _open_case_or_fail(case_dir)
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

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
from witnessgraph.core.tracked_finding import FindingStatus, TrackedGapFinding
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.correlate.gaps import DEFAULT_MIN_CORROBORATING_EVENTS, find_gaps
from witnessgraph.correlate.tracking import is_still_reproduced, track_findings
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
findings_app = typer.Typer(
    help="Inspect and annotate persisted, tracked gap-analysis findings (v0.7).",
    no_args_is_help=True,
)
app.add_typer(entities_app, name="entities")
app.add_typer(hypothesis_app, name="hypothesis")
app.add_typer(findings_app, name="findings")


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
    case = Case.open(case_dir)
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
    case = Case.open(case_dir)
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
    case = Case.open(case_dir)
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
    case = Case.open(case_dir)
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

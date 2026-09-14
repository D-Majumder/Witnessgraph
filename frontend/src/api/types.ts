// Mirrors witnessgraph's own JSON contracts exactly (see
// docs/phase-ui-v1-architecture-design.md §5 and the *_to_json builders
// in correlate/graph.py, correlate/contradictions.py, correlate/overview.py).
// This file is a type projection of those contracts, never a redefinition
// of them -- if a field here drifts from the backend, that is a bug in
// this file, not an alternate source of truth.

export type GraphDirection = 'out' | 'in' | 'both'

export interface EvidenceItem {
  id: string
  source_adapter: string
  adapter_version: string
  source_locator: string
  raw_size_bytes: number
  collected_at: string
  observed_at: string | null
}

export interface NormalizedEvent {
  id: string
  event_type: string
  attributes: Record<string, unknown>
  derived_from: string[]
}

export type ResolvedEvidenceRefKind = 'evidence_item' | 'normalized_event' | 'not_found'

export interface ResolvedEvidenceRef {
  id: string
  kind: ResolvedEvidenceRefKind
  evidence_item: EvidenceItem | null
  normalized_event: NormalizedEvent | null
}

export interface Entity {
  id: string
  entity_type: string
  identifiers: Record<string, string>
  first_seen: string | null
  last_seen: string | null
  derived_from: string[]
}

export interface Relationship {
  id: string
  relationship_type: string
  source_entity_id: string
  target_entity_id: string
  attributes: Record<string, string>
  derived_from: string[]
  // Always present on GET /relationships/{id} and inside every graph
  // result (the API never omits it -- see §14's "always resolved" note).
  evidence_lineage?: ResolvedEvidenceRef[]
}

export interface ResolvedEntity {
  entity_id: string
  found: boolean
  entity_type: string | null
  identifiers: Record<string, string> | null
}

export type WalkedDirection = 'forward' | 'backward'

export interface TraversalStep {
  from_entity_id: string
  to_entity_id: string
  walked_direction: WalkedDirection
  relationship: Relationship
}

export interface ReachableEntity {
  entity_id: string
  hop_count: number
  via: TraversalStep
}

export interface NeighborsResult {
  origin_entity_id: string
  direction: GraphDirection
  max_depth: number
  reached: ReachableEntity[]
  entities?: Record<string, ResolvedEntity>
}

export interface PathResult {
  source_entity_id: string
  target_entity_id: string
  direction: GraphDirection
  max_depth: number
  found: boolean
  hop_count: number | null
  steps: TraversalStep[]
  entities?: Record<string, ResolvedEntity>
}

export interface ChainEvidence {
  chain_index: number
  root_evidence_ids: string[]
}

export interface PathsEvidenceOverlap {
  chains: ChainEvidence[]
  shared_evidence_ids: string[]
  // Never a bare `true`/`false` default -- `null` means "fewer than 2
  // chains, the question does not apply" and must be rendered as such.
  fully_evidence_independent: boolean | null
}

export interface AllShortestPathsResult {
  source_entity_id: string
  target_entity_id: string
  direction: GraphDirection
  max_depth: number
  limit: number
  found: boolean
  hop_count: number | null
  truncated: boolean
  paths: TraversalStep[][]
  entities?: Record<string, ResolvedEntity>
  evidence_independence?: PathsEvidenceOverlap
}

export interface GraphComponent {
  index: number
  entity_ids: string[]
  relationships: Relationship[]
}

export interface ComponentsResult {
  min_size: number
  total_entities_in_graph: number
  total_relationships: number
  total_components_found: number
  components: GraphComponent[]
  entities?: Record<string, ResolvedEntity>
}

export interface CaseOverview {
  case_name: string
  evidence_count: number
  normalized_event_count: number
  entity_count: number
  relationship_count: number
  hypothesis_count: number
  tracked_finding_count: number
  tracked_contradiction_count: number
  manifest_hash: string
  manifest_verdict: 'MATCH' | 'MISMATCH' | 'NOT_COMPARABLE' | 'NO_RECORDED_MANIFEST'
}

export interface TimeAssertionSummary {
  id: string
  value: string
  precision: string
  source_evidence_id: string
}

export interface Contradiction {
  subject_event_id: string
  assertions: TimeAssertionSummary[]
}

export type FindingStatus = 'open' | 'reviewed' | 'dismissed'

export interface GapFinding {
  absent_source: string
  present_source: string
  absent_source_refinement: string | null
  present_source_refinement: string | null
  interval_start: string
  interval_end: string
  corroborating_time_assertion_ids: string[]
  bounding_absent_assertion_ids: [string, string]
}

export interface GapAnalysisResult {
  refine_source_by_attribute: string | null
  findings: GapFinding[]
  excluded_no_time_assertion: number
  excluded_no_declared_source: number
  excluded_ambiguous_source: number
  excluded_unrefined_fallback_with_refined_sibling: number
}

export interface TrackedGapFinding {
  id: string
  absent_source: string
  present_source: string
  absent_source_refinement: string | null
  present_source_refinement: string | null
  interval_start: string
  interval_end: string
  corroborating_time_assertion_ids: string[]
  bounding_absent_assertion_ids: [string, string]
  min_gap_seconds: number
  min_corroborating_events: number
  refine_source_by_attribute: string | null
  status: FindingStatus
  annotated_by: string | null
  annotated_at: string | null
  note: string | null
  // Live-recomputed, never persisted -- see correlate.tracking.is_still_reproduced.
  still_reproduced: boolean
}

export interface TrackedTimeContradiction {
  id: string
  subject_event_id: string
  assertion_ids: [string, string]
  status: FindingStatus
  annotated_by: string | null
  annotated_at: string | null
  note: string | null
  // Deliberately absent from the engine's own JSON shape -- an
  // always-true value would convey no information. Never add it here.
}

export interface TrackSummary {
  new: number
  already_tracked: number
}

export interface TimelineEntry {
  id: string
  event_type: string
  entity_ids: string[]
  derived_from: string[]
  attributes: Record<string, unknown>
  time_assertions: TimeAssertionSummary[]
}

// Thin fetch wrapper over the local-only Witnessgraph API. Never talks to
// SQLite/case files directly -- every fact the UI shows comes through
// one of these calls, which map 1:1 onto witnessgraph.api's routes (see
// docs/phase-ui-v1-architecture-design.md §14). No client-side caching
// or re-derivation of analysis happens here; that stays in the backend.

import type {
  AllShortestPathsResult,
  CaseOverview,
  ComponentsResult,
  Contradiction,
  Entity,
  EvidenceItem,
  FindingStatus,
  GapAnalysisResult,
  GraphDirection,
  NeighborsResult,
  PathResult,
  Relationship,
  ResolvedEvidenceRef,
  TimelineEntry,
  TrackedGapFinding,
  TrackedTimeContradiction,
  TrackSummary,
} from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8420'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  params?: Record<string, string | number | undefined>
  method?: 'GET' | 'POST'
  json?: unknown
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(path, BASE_URL)
  if (options.params) {
    for (const [key, value] of Object.entries(options.params)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
  }
  let response: Response
  try {
    response = await fetch(url, {
      method: options.method ?? 'GET',
      headers: options.json !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: options.json !== undefined ? JSON.stringify(options.json) : undefined,
    })
  } catch {
    throw new ApiError(0, `Could not reach the Witnessgraph API at ${BASE_URL}`)
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // response body was not JSON -- fall back to statusText
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export function getCaseOverview(): Promise<CaseOverview> {
  return request('/case')
}

export function listEntities(entityType?: string): Promise<Entity[]> {
  return request('/entities', { params: { entity_type: entityType } })
}

export function getEntity(entityId: string): Promise<Entity> {
  return request(`/entities/${encodeURIComponent(entityId)}`)
}

export function listRelationships(filters?: {
  entityId?: string
  relationshipType?: string
}): Promise<Relationship[]> {
  return request('/relationships', {
    params: {
      entity_id: filters?.entityId,
      relationship_type: filters?.relationshipType,
    },
  })
}

export function getRelationship(relationshipId: string): Promise<Relationship> {
  return request(`/relationships/${encodeURIComponent(relationshipId)}`)
}

export function listEvidence(sourceAdapter?: string): Promise<EvidenceItem[]> {
  return request('/evidence', { params: { source_adapter: sourceAdapter } })
}

export function resolveEvidence(refId: string): Promise<ResolvedEvidenceRef> {
  return request(`/evidence/${encodeURIComponent(refId)}`)
}

export function getNeighbors(params: {
  entityId: string
  maxDepth?: number
  direction?: GraphDirection
}): Promise<NeighborsResult> {
  return request('/graph/neighbors', {
    params: {
      entity_id: params.entityId,
      max_depth: params.maxDepth,
      direction: params.direction,
    },
  })
}

export function getPath(params: {
  sourceEntityId: string
  targetEntityId: string
  maxDepth?: number
  direction?: GraphDirection
}): Promise<PathResult> {
  return request('/graph/path', {
    params: {
      source_entity_id: params.sourceEntityId,
      target_entity_id: params.targetEntityId,
      max_depth: params.maxDepth,
      direction: params.direction,
    },
  })
}

export function getPaths(params: {
  sourceEntityId: string
  targetEntityId: string
  maxDepth?: number
  direction?: GraphDirection
  limit?: number
}): Promise<AllShortestPathsResult> {
  return request('/graph/paths', {
    params: {
      source_entity_id: params.sourceEntityId,
      target_entity_id: params.targetEntityId,
      max_depth: params.maxDepth,
      direction: params.direction,
      limit: params.limit,
    },
  })
}

export function getComponents(minSize?: number): Promise<ComponentsResult> {
  return request('/graph/components', { params: { min_size: minSize } })
}

export function listContradictions(): Promise<Contradiction[]> {
  return request('/contradictions')
}

export function trackContradictions(): Promise<TrackSummary> {
  return request('/contradictions/track', { method: 'POST' })
}

export function listContradictionFindings(): Promise<TrackedTimeContradiction[]> {
  return request('/contradiction-findings')
}

export function ackContradictionFinding(
  contradictionId: string,
  ack: { status: FindingStatus; by: string; note?: string },
): Promise<TrackedTimeContradiction> {
  return request(`/contradiction-findings/${encodeURIComponent(contradictionId)}/ack`, {
    method: 'POST',
    json: ack,
  })
}

export function getTimeline(eventType?: string): Promise<TimelineEntry[]> {
  return request('/timeline', { params: { event_type: eventType } })
}

export function analyzeGaps(params: {
  minGapSeconds: number
  minCorroboratingEvents?: number
  refineSourceByAttribute?: string
}): Promise<GapAnalysisResult> {
  return request('/gaps', {
    params: {
      min_gap_seconds: params.minGapSeconds,
      min_corroborating_events: params.minCorroboratingEvents,
      refine_source_by_attribute: params.refineSourceByAttribute,
    },
  })
}

export function trackGaps(params: {
  minGapSeconds: number
  minCorroboratingEvents?: number
  refineSourceByAttribute?: string
}): Promise<TrackSummary> {
  return request('/gaps/track', {
    method: 'POST',
    params: {
      min_gap_seconds: params.minGapSeconds,
      min_corroborating_events: params.minCorroboratingEvents,
      refine_source_by_attribute: params.refineSourceByAttribute,
    },
  })
}

export function listFindings(): Promise<TrackedGapFinding[]> {
  return request('/findings')
}

export function ackFinding(
  findingId: string,
  ack: { status: FindingStatus; by: string; note?: string },
): Promise<TrackedGapFinding> {
  return request(`/findings/${encodeURIComponent(findingId)}/ack`, {
    method: 'POST',
    json: ack,
  })
}

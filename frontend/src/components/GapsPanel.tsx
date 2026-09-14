// Cross-source coverage-gap analysis. min_gap_seconds has no default the
// engine claims is objectively correct -- the analyst must choose one;
// this view never silently picks a value for them.
//
// CRITICAL WORDING: a finding here means "no observed evidence from the
// declared absent source in this interval, while the present source has
// corroborating activity" -- it is NEVER rendered as "the event did not
// happen". See the engine's own GapFinding/correlate.gaps docstrings.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { analyzeGaps, trackGaps } from '../api/client'
import type { GapAnalysisResult } from '../api/types'

function formatSource(source: string, refinement: string | null): string {
  return refinement ? `${source} (refined: ${refinement})` : source
}

export function GapsPanel() {
  const queryClient = useQueryClient()
  const [minGapSeconds, setMinGapSeconds] = useState(3600)
  const [minCorroboratingEvents, setMinCorroboratingEvents] = useState(2)
  const [refineByAttribute, setRefineByAttribute] = useState('')
  const [result, setResult] = useState<GapAnalysisResult | null>(null)

  const analyzeMutation = useMutation({
    mutationFn: () =>
      analyzeGaps({
        minGapSeconds,
        minCorroboratingEvents,
        refineSourceByAttribute: refineByAttribute || undefined,
      }),
    onSuccess: setResult,
  })

  const trackMutation = useMutation({
    mutationFn: () =>
      trackGaps({
        minGapSeconds,
        minCorroboratingEvents,
        refineSourceByAttribute: refineByAttribute || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['findings'] })
      queryClient.invalidateQueries({ queryKey: ['case'] })
    },
  })

  const error = analyzeMutation.error ?? trackMutation.error

  return (
    <div className="view-panel" data-testid="gaps-panel">
      <h2>Gaps</h2>
      <p className="provenance-caption">
        A finding means: the declared "absent" source has no observed evidence in the stated
        interval, while a different, independently-declared source has corroborating activity
        there. This is <strong>never</strong> a claim that an event did not happen -- only that no
        matching evidence from that source was found for it.
      </p>
      <div className="path-controls">
        <label>
          Min gap seconds (required)
          <input
            type="number"
            min={0}
            step="any"
            value={minGapSeconds}
            onChange={(event) => setMinGapSeconds(Number(event.target.value))}
          />
        </label>
        <label>
          Min corroborating events
          <input
            type="number"
            min={1}
            value={minCorroboratingEvents}
            onChange={(event) => setMinCorroboratingEvents(Number(event.target.value))}
          />
        </label>
        <label>
          Refine source by attribute (optional)
          <input
            type="text"
            value={refineByAttribute}
            onChange={(event) => setRefineByAttribute(event.target.value)}
            placeholder="e.g. host"
          />
        </label>
      </div>
      <div className="path-actions">
        <button type="button" onClick={() => analyzeMutation.mutate()} disabled={analyzeMutation.isPending}>
          Analyze
        </button>
        {result && result.findings.length > 0 && (
          <button type="button" onClick={() => trackMutation.mutate()} disabled={trackMutation.isPending}>
            Track findings
          </button>
        )}
      </div>
      {error && <p className="error-text">{(error as Error).message}</p>}
      {trackMutation.data && (
        <p className="track-summary">
          {trackMutation.data.new} new, {trackMutation.data.already_tracked} already tracked. See
          Findings to review.
        </p>
      )}
      {result && (
        <div data-testid="gaps-result">
          {result.findings.length === 0 ? (
            <p className="empty-note">No coverage gaps found at this threshold.</p>
          ) : (
            <ul>
              {result.findings.map((finding, i) => (
                <li key={i}>
                  No evidence from{' '}
                  <strong>
                    {formatSource(finding.absent_source, finding.absent_source_refinement)}
                  </strong>{' '}
                  in [{finding.interval_start}, {finding.interval_end}), while{' '}
                  <strong>
                    {formatSource(finding.present_source, finding.present_source_refinement)}
                  </strong>{' '}
                  has {finding.corroborating_time_assertion_ids.length} corroborating event(s) in
                  that window.
                </li>
              ))}
            </ul>
          )}
          <p className="provenance-caption">
            Excluded: {result.excluded_no_time_assertion} event(s) with no time assertion,{' '}
            {result.excluded_no_declared_source} assertion(s) with no declared source,{' '}
            {result.excluded_ambiguous_source} assertion(s) with ambiguous declared source.
          </p>
        </div>
      )}
    </div>
  )
}

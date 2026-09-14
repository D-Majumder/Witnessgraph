// Structural TimeAssertion contradictions. The one write action exposed
// here is "track" -- persisting each detected contradiction with a
// stable id so it can be reviewed later (see FindingsPanel). Tracking
// never adjudicates which assertion is correct.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listContradictions, trackContradictions } from '../api/client'

export function ContradictionsPanel() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['contradictions'], queryFn: listContradictions })
  const trackMutation = useMutation({
    mutationFn: trackContradictions,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['contradiction-findings'] })
      queryClient.invalidateQueries({ queryKey: ['case'] })
    },
  })

  return (
    <div className="view-panel" data-testid="contradictions-panel">
      <h2>Contradictions</h2>
      <p className="provenance-caption">
        Two TimeAssertions about the same event that cannot both be true. Neither assertion is
        marked as "the truth" -- this only reports that they disagree. Witnessgraph does not
        determine which claim is correct.
      </p>
      {query.isLoading && <p>Loading contradictions...</p>}
      {query.isError && <p className="error-text">{(query.error as Error).message}</p>}
      {query.data && query.data.length === 0 && (
        <p className="empty-note">No structural time contradictions detected in this case.</p>
      )}
      {query.data && query.data.length > 0 && (
        <>
          <button type="button" onClick={() => trackMutation.mutate()} disabled={trackMutation.isPending}>
            Track as findings
          </button>
          {trackMutation.data && (
            <p className="track-summary">
              {trackMutation.data.new} new, {trackMutation.data.already_tracked} already tracked.
              See Findings to review.
            </p>
          )}
          <ul>
            {query.data.map((c) => (
              <li key={`${c.subject_event_id}-${c.assertions.map((a) => a.id).join('-')}`}>
                <strong>Event</strong> <code>{c.subject_event_id}</code>
                <ul>
                  {c.assertions.map((a) => (
                    <li key={a.id}>
                      <code>{a.id}</code>: {a.value} (precision: {a.precision}, source:{' '}
                      <code>{a.source_evidence_id}</code>)
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

// Tracked gap findings + tracked contradiction findings: the one review/
// acknowledgement workflow this engine has. A status of "reviewed" means
// only "an analyst looked at this" -- never "validated" or "confirmed",
// and no such status is ever offered.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ackContradictionFinding, ackFinding, listContradictionFindings, listFindings } from '../api/client'
import type { FindingStatus, TrackedGapFinding, TrackedTimeContradiction } from '../api/types'

const STATUS_OPTIONS: FindingStatus[] = ['open', 'reviewed', 'dismissed']

function AckForm({ onSubmit, pending }: { onSubmit: (status: FindingStatus, by: string, note: string) => void; pending: boolean }) {
  const [status, setStatus] = useState<FindingStatus>('reviewed')
  const [by, setBy] = useState('')
  const [note, setNote] = useState('')

  return (
    <form
      className="ack-form"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit(status, by, note)
      }}
    >
      <select value={status} onChange={(event) => setStatus(event.target.value as FindingStatus)}>
        {STATUS_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <input
        type="text"
        placeholder="your identity (required)"
        value={by}
        onChange={(event) => setBy(event.target.value)}
        required
      />
      <input
        type="text"
        placeholder="note (optional)"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <button type="submit" disabled={pending || !by.trim()}>
        Acknowledge
      </button>
    </form>
  )
}

function GapFindingRow({ finding }: { finding: TrackedGapFinding }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (vars: { status: FindingStatus; by: string; note: string }) =>
      ackFinding(finding.id, { status: vars.status, by: vars.by, note: vars.note || undefined }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['findings'] }),
  })

  return (
    <li>
      <div>
        No evidence from <strong>{finding.absent_source}</strong> in [{finding.interval_start},{' '}
        {finding.interval_end}) while <strong>{finding.present_source}</strong> has corroborating
        activity.
      </div>
      <div className="finding-meta">
        status: <strong>{finding.status}</strong>
        {finding.annotated_by && ` (by ${finding.annotated_by})`} · still reproduced by current
        evidence:{' '}
        <strong>{finding.still_reproduced ? 'yes' : 'no'}</strong>
      </div>
      {finding.note && <div className="finding-note">note: {finding.note}</div>}
      <AckForm pending={mutation.isPending} onSubmit={(status, by, note) => mutation.mutate({ status, by, note })} />
      {mutation.isError && <p className="error-text">{(mutation.error as Error).message}</p>}
    </li>
  )
}

function ContradictionFindingRow({ finding }: { finding: TrackedTimeContradiction }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (vars: { status: FindingStatus; by: string; note: string }) =>
      ackContradictionFinding(finding.id, {
        status: vars.status,
        by: vars.by,
        note: vars.note || undefined,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['contradiction-findings'] }),
  })

  return (
    <li>
      <div>
        Contradiction on event <code>{finding.subject_event_id}</code> (assertions{' '}
        <code>{finding.assertion_ids[0]}</code>, <code>{finding.assertion_ids[1]}</code>)
      </div>
      <div className="finding-meta">
        status: <strong>{finding.status}</strong>
        {finding.annotated_by && ` (by ${finding.annotated_by})`}
      </div>
      {finding.note && <div className="finding-note">note: {finding.note}</div>}
      <AckForm pending={mutation.isPending} onSubmit={(status, by, note) => mutation.mutate({ status, by, note })} />
      {mutation.isError && <p className="error-text">{(mutation.error as Error).message}</p>}
    </li>
  )
}

export function FindingsPanel() {
  const findingsQuery = useQuery({ queryKey: ['findings'], queryFn: listFindings })
  const contradictionFindingsQuery = useQuery({
    queryKey: ['contradiction-findings'],
    queryFn: listContradictionFindings,
  })

  return (
    <div className="view-panel" data-testid="findings-panel">
      <h2>Findings</h2>
      <p className="provenance-caption">
        Tracked, persisted structural findings, with an optional analyst review annotation. A
        "reviewed" status means only that an analyst looked at this -- never that it was
        validated, confirmed, or that an absent event should have existed.
      </p>

      <h3>Tracked gap findings</h3>
      {findingsQuery.isLoading && <p>Loading...</p>}
      {findingsQuery.isError && <p className="error-text">{(findingsQuery.error as Error).message}</p>}
      {findingsQuery.data && findingsQuery.data.length === 0 && (
        <p className="empty-note">No gap findings tracked yet -- track some from the Gaps view.</p>
      )}
      {findingsQuery.data && findingsQuery.data.length > 0 && (
        <ul className="findings-list">
          {findingsQuery.data.map((finding) => (
            <GapFindingRow key={finding.id} finding={finding} />
          ))}
        </ul>
      )}

      <h3>Tracked contradiction findings</h3>
      {contradictionFindingsQuery.isLoading && <p>Loading...</p>}
      {contradictionFindingsQuery.isError && (
        <p className="error-text">{(contradictionFindingsQuery.error as Error).message}</p>
      )}
      {contradictionFindingsQuery.data && contradictionFindingsQuery.data.length === 0 && (
        <p className="empty-note">
          No contradictions tracked yet -- track some from the Contradictions view.
        </p>
      )}
      {contradictionFindingsQuery.data && contradictionFindingsQuery.data.length > 0 && (
        <ul className="findings-list">
          {contradictionFindingsQuery.data.map((finding) => (
            <ContradictionFindingRow key={finding.id} finding={finding} />
          ))}
        </ul>
      )}
    </div>
  )
}

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { TrackedGapFinding, TrackedTimeContradiction } from '../api/types'
import { FindingsPanel } from './FindingsPanel'

vi.mock('../api/client', () => ({
  listFindings: vi.fn(),
  listContradictionFindings: vi.fn(),
  ackFinding: vi.fn(),
  ackContradictionFinding: vi.fn(),
}))

import {
  ackContradictionFinding,
  ackFinding,
  listContradictionFindings,
  listFindings,
} from '../api/client'

const gapFinding: TrackedGapFinding = {
  id: 'finding-1',
  absent_source: 'hostA',
  present_source: 'hostB',
  absent_source_refinement: null,
  present_source_refinement: null,
  interval_start: '2026-01-01T00:00:00Z',
  interval_end: '2026-01-01T01:00:00Z',
  corroborating_time_assertion_ids: ['ta-1'],
  bounding_absent_assertion_ids: ['ta-0', 'ta-2'],
  min_gap_seconds: 60,
  min_corroborating_events: 2,
  refine_source_by_attribute: null,
  status: 'open',
  annotated_by: null,
  annotated_at: null,
  note: null,
  still_reproduced: true,
}

const contradictionFinding: TrackedTimeContradiction = {
  id: 'contradiction-1',
  subject_event_id: 'event-1',
  assertion_ids: ['ta-1', 'ta-2'],
  status: 'open',
  annotated_by: null,
  annotated_at: null,
  note: null,
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <FindingsPanel />
    </QueryClientProvider>,
  )
}

describe('FindingsPanel', () => {
  beforeEach(() => {
    vi.mocked(listFindings).mockReset()
    vi.mocked(listContradictionFindings).mockReset()
    vi.mocked(ackFinding).mockReset()
    vi.mocked(ackContradictionFinding).mockReset()
  })

  it('shows useful empty states for both finding kinds', async () => {
    vi.mocked(listFindings).mockResolvedValue([])
    vi.mocked(listContradictionFindings).mockResolvedValue([])
    renderPanel()

    expect(await screen.findByText(/No gap findings tracked yet/)).toBeInTheDocument()
    expect(screen.getByText(/No contradictions tracked yet/)).toBeInTheDocument()
  })

  it('only ever offers open/reviewed/dismissed as acknowledgement statuses', async () => {
    vi.mocked(listFindings).mockResolvedValue([gapFinding])
    vi.mocked(listContradictionFindings).mockResolvedValue([])
    renderPanel()

    await screen.findByText(/No evidence from/)
    const select = screen.getByRole('combobox') as HTMLSelectElement
    const options = Array.from(select.options).map((o) => o.value)
    expect(options.sort()).toEqual(['dismissed', 'open', 'reviewed'])
  })

  it('acknowledging a gap finding requires a non-blank identity and never says "validated"', async () => {
    vi.mocked(listFindings).mockResolvedValue([gapFinding])
    vi.mocked(listContradictionFindings).mockResolvedValue([])
    vi.mocked(ackFinding).mockResolvedValue({ ...gapFinding, status: 'reviewed', annotated_by: 'analyst1' })
    const user = userEvent.setup()
    renderPanel()

    await screen.findByText(/No evidence from/)
    const submitButton = screen.getByRole('button', { name: 'Acknowledge' })
    expect(submitButton).toBeDisabled()

    await user.type(screen.getByPlaceholderText('your identity (required)'), 'analyst1')
    expect(submitButton).toBeEnabled()
    await user.click(submitButton)

    expect(ackFinding).toHaveBeenCalledWith('finding-1', { status: 'reviewed', by: 'analyst1', note: undefined })
    // The panel's own caption legitimately says "never ... validated" as a
    // negation; the status vocabulary offered/rendered must not include it.
    const select = screen.getByRole('combobox') as HTMLSelectElement
    const options = Array.from(select.options).map((o) => o.value)
    expect(options).not.toContain('validated')
    expect(options).not.toContain('confirmed')
  })

  it('acknowledging a contradiction finding never implies which assertion is true', async () => {
    vi.mocked(listFindings).mockResolvedValue([])
    vi.mocked(listContradictionFindings).mockResolvedValue([contradictionFinding])
    vi.mocked(ackContradictionFinding).mockResolvedValue({
      ...contradictionFinding,
      status: 'dismissed',
      annotated_by: 'analyst2',
    })
    const user = userEvent.setup()
    renderPanel()

    await screen.findByText(/Contradiction on event/)
    await user.type(screen.getByPlaceholderText('your identity (required)'), 'analyst2')
    await user.click(screen.getByRole('button', { name: 'Acknowledge' }))

    expect(ackContradictionFinding).toHaveBeenCalledWith('contradiction-1', {
      status: 'reviewed',
      by: 'analyst2',
      note: undefined,
    })
  })
})

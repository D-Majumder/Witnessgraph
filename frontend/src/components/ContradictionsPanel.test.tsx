import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Contradiction, TrackSummary } from '../api/types'
import { ContradictionsPanel } from './ContradictionsPanel'

vi.mock('../api/client', () => ({
  listContradictions: vi.fn(),
  trackContradictions: vi.fn(),
}))

import { listContradictions, trackContradictions } from '../api/client'

const contradiction: Contradiction = {
  subject_event_id: 'event-1',
  assertions: [
    { id: 'ta-1', value: '2026-01-01T00:00:00Z', precision: 'second', source_evidence_id: 'ev-1' },
    { id: 'ta-2', value: '2026-01-01T01:00:00Z', precision: 'second', source_evidence_id: 'ev-2' },
  ],
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ContradictionsPanel />
    </QueryClientProvider>,
  )
}

describe('ContradictionsPanel', () => {
  beforeEach(() => {
    vi.mocked(listContradictions).mockReset()
    vi.mocked(trackContradictions).mockReset()
  })

  it('shows a useful empty state when there are no contradictions', async () => {
    vi.mocked(listContradictions).mockResolvedValue([])
    renderPanel()
    expect(await screen.findByText(/No structural time contradictions/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Track as findings' })).not.toBeInTheDocument()
  })

  it('never marks either assertion as the truth', async () => {
    vi.mocked(listContradictions).mockResolvedValue([contradiction])
    renderPanel()
    await screen.findByText('event-1')
    expect(document.body.textContent).not.toMatch(/resolved|adjudicated|correct assertion/i)
  })

  it('tracking shows the new/already_tracked summary', async () => {
    vi.mocked(listContradictions).mockResolvedValue([contradiction])
    const summary: TrackSummary = { new: 1, already_tracked: 0 }
    vi.mocked(trackContradictions).mockResolvedValue(summary)
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Track as findings' }))

    expect(await screen.findByText(/1 new, 0 already tracked/)).toBeInTheDocument()
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineEntry } from '../api/types'
import { TimelinePanel } from './TimelinePanel'

vi.mock('../api/client', () => ({
  getTimeline: vi.fn(),
}))

import { getTimeline } from '../api/client'

const entry: TimelineEntry = {
  id: 'event-1',
  event_type: 'logon',
  entity_ids: [],
  derived_from: ['ev-1'],
  attributes: { host: 'ws-01' },
  time_assertions: [
    { id: 'ta-1', value: '2026-01-01T00:00:00Z', precision: 'second', source_evidence_id: 'ev-1' },
  ],
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <TimelinePanel />
    </QueryClientProvider>,
  )
}

describe('TimelinePanel', () => {
  beforeEach(() => {
    vi.mocked(getTimeline).mockReset()
  })

  it('shows a useful empty state', async () => {
    vi.mocked(getTimeline).mockResolvedValue([])
    renderPanel()
    expect(await screen.findByText(/No events in this case yet/)).toBeInTheDocument()
  })

  it('expands to show time assertions on click, collapsed by default', async () => {
    vi.mocked(getTimeline).mockResolvedValue([entry])
    const user = userEvent.setup()
    renderPanel()

    await screen.findByText('logon')
    expect(screen.queryByText(/precision: second/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /logon/ }))
    expect(screen.getByText(/precision: second/)).toBeInTheDocument()
  })
})

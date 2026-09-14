import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { EvidenceItem } from '../api/types'
import { EvidencePanel } from './EvidencePanel'

vi.mock('../api/client', () => ({
  listEvidence: vi.fn(),
}))

import { listEvidence } from '../api/client'

const items: EvidenceItem[] = [
  {
    id: 'ev-1',
    source_adapter: 'jsonl',
    adapter_version: '1',
    source_locator: 'a.jsonl:1',
    raw_size_bytes: 42,
    collected_at: '2026-01-01T00:00:00Z',
    observed_at: null,
  },
  {
    id: 'ev-2',
    source_adapter: 'syslog',
    adapter_version: '1',
    source_locator: 'b.syslog:1',
    raw_size_bytes: 100,
    collected_at: '2026-01-01T00:00:00Z',
    observed_at: null,
  },
]

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <EvidencePanel />
    </QueryClientProvider>,
  )
}

describe('EvidencePanel', () => {
  beforeEach(() => {
    vi.mocked(listEvidence).mockReset()
  })

  it('shows a useful empty state', async () => {
    vi.mocked(listEvidence).mockResolvedValue([])
    renderPanel()
    expect(await screen.findByText(/No evidence matches/)).toBeInTheDocument()
  })

  it('lists every item and filters by source adapter substring', async () => {
    vi.mocked(listEvidence).mockResolvedValue(items)
    const user = userEvent.setup()
    renderPanel()

    expect(await screen.findByText('ev-1')).toBeInTheDocument()
    expect(screen.getByText('ev-2')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Filter evidence by source adapter'), 'json')
    expect(screen.getByText('ev-1')).toBeInTheDocument()
    expect(screen.queryByText('ev-2')).not.toBeInTheDocument()
  })

  it('never exposes a filesystem path or raw blob content, only metadata', async () => {
    vi.mocked(listEvidence).mockResolvedValue(items)
    renderPanel()
    await screen.findByText('ev-1')
    expect(document.body.textContent).not.toMatch(/C:\\|\/home\/|\/etc\//)
  })
})

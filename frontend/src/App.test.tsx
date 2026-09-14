import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError } from './api/client'
import type { CaseOverview, Entity, Relationship } from './api/types'

// jsdom has no 2D canvas backing, which Cytoscape's renderer requires --
// the graph-data-transformation logic itself is covered in isolation by
// graph/elements.test.ts. Here we only need App's own state wiring
// (selection, panels, path results), so Cytoscape is replaced with a
// minimal no-op stub.
vi.mock('cytoscape', () => {
  const fakeCore = {
    on: vi.fn(),
    style: vi.fn().mockReturnThis(),
    elements: vi.fn().mockReturnValue({ remove: vi.fn() }),
    add: vi.fn(),
    layout: vi.fn().mockReturnValue({ run: vi.fn() }),
    destroy: vi.fn(),
  }
  return { default: vi.fn(() => fakeCore) }
})

vi.mock('./api/client', async () => {
  const actual = await vi.importActual<typeof import('./api/client')>('./api/client')
  return {
    ...actual,
    getCaseOverview: vi.fn(),
    listEntities: vi.fn(),
    listRelationships: vi.fn(),
    listContradictions: vi.fn(),
    getRelationship: vi.fn(),
    getComponents: vi.fn(),
    listEvidence: vi.fn(),
    getTimeline: vi.fn(),
    listFindings: vi.fn(),
    listContradictionFindings: vi.fn(),
  }
})

import {
  getCaseOverview,
  getComponents,
  getRelationship,
  getTimeline,
  listContradictionFindings,
  listContradictions,
  listEntities,
  listEvidence,
  listFindings,
  listRelationships,
} from './api/client'

const overview: CaseOverview = {
  case_name: 'demo-case',
  evidence_count: 1,
  normalized_event_count: 0,
  entity_count: 2,
  relationship_count: 1,
  hypothesis_count: 0,
  tracked_finding_count: 0,
  tracked_contradiction_count: 0,
  manifest_hash: 'abc123',
  manifest_verdict: 'MATCH',
}

const entities: Entity[] = [
  { id: 'e-a', entity_type: 'host', identifiers: { hostname: 'a' }, first_seen: null, last_seen: null, derived_from: ['ev-1'] },
  { id: 'e-b', entity_type: 'host', identifiers: { hostname: 'b' }, first_seen: null, last_seen: null, derived_from: ['ev-1'] },
]

const relationships: Relationship[] = [
  {
    id: 'r-1',
    relationship_type: 'connected_to',
    source_entity_id: 'e-a',
    target_entity_id: 'e-b',
    attributes: {},
    derived_from: ['ev-1'],
  },
]

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

describe('App', () => {
  beforeEach(() => {
    vi.mocked(getCaseOverview).mockReset()
    vi.mocked(listEntities).mockReset()
    vi.mocked(listRelationships).mockReset()
    vi.mocked(listContradictions).mockReset().mockResolvedValue([])
    vi.mocked(getRelationship).mockReset().mockResolvedValue({
      ...relationships[0],
      evidence_lineage: [
        { id: 'ev-1', kind: 'evidence_item', evidence_item: null, normalized_event: null },
      ],
    })
    vi.mocked(getComponents).mockReset().mockResolvedValue({
      min_size: 1,
      total_entities_in_graph: 2,
      total_relationships: 1,
      total_components_found: 1,
      components: [{ index: 0, entity_ids: ['e-a', 'e-b'], relationships }],
    })
    vi.mocked(listEvidence).mockReset().mockResolvedValue([])
    vi.mocked(getTimeline).mockReset().mockResolvedValue([])
    vi.mocked(listFindings).mockReset().mockResolvedValue([])
    vi.mocked(listContradictionFindings).mockReset().mockResolvedValue([])
  })

  it('shows a loading state, then the case overview once data arrives', async () => {
    vi.mocked(getCaseOverview).mockResolvedValue(overview)
    vi.mocked(listEntities).mockResolvedValue(entities)
    vi.mocked(listRelationships).mockResolvedValue(relationships)

    renderApp()

    expect(screen.getByText(/Connecting to the Witnessgraph API/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('case-header')).toBeInTheDocument())
    expect(screen.getByText('demo-case')).toBeInTheDocument()
    expect(screen.getByText(/Manifest verified/)).toBeInTheDocument()
  })

  it('shows the error screen with the exact startup command when the API is unreachable', async () => {
    vi.mocked(getCaseOverview).mockRejectedValue(new ApiError(0, 'Could not reach the Witnessgraph API at http://127.0.0.1:8420'))

    renderApp()

    await waitFor(() => expect(screen.getByTestId('error-screen')).toBeInTheDocument())
    expect(screen.getByText(/witnessgraph-api path\/to\/case-directory/)).toBeInTheDocument()
  })

  it('selecting an entity from the list opens its detail panel with provenance', async () => {
    vi.mocked(getCaseOverview).mockResolvedValue(overview)
    vi.mocked(listEntities).mockResolvedValue(entities)
    vi.mocked(listRelationships).mockResolvedValue(relationships)
    const user = userEvent.setup()

    renderApp()
    await waitFor(() => expect(screen.getByTestId('case-header')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /host: a/ }))

    expect(screen.getByTestId('entity-detail')).toBeInTheDocument()
    expect(screen.getByText('ev-1')).toBeInTheDocument()
  })

  it('selecting a relationship shows its panel and clears the entity selection', async () => {
    vi.mocked(getCaseOverview).mockResolvedValue(overview)
    vi.mocked(listEntities).mockResolvedValue(entities)
    vi.mocked(listRelationships).mockResolvedValue(relationships)
    const user = userEvent.setup()

    renderApp()
    await waitFor(() => expect(screen.getByTestId('case-header')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /host: a/ }))
    expect(screen.getByTestId('entity-detail')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Relationships' }))
    await user.click(screen.getByRole('button', { name: /e-a.*connected_to.*e-b/ }))

    expect(screen.queryByTestId('entity-detail')).not.toBeInTheDocument()
    expect(screen.getByTestId('relationship-detail')).toBeInTheDocument()
  })

  it.each([
    ['Evidence', 'evidence-panel'],
    ['Timeline', 'timeline-panel'],
    ['Contradictions', 'contradictions-panel'],
    ['Gaps', 'gaps-panel'],
    ['Findings', 'findings-panel'],
  ])('top-nav switches to the %s view', async (navLabel, testId) => {
    vi.mocked(getCaseOverview).mockResolvedValue(overview)
    vi.mocked(listEntities).mockResolvedValue(entities)
    vi.mocked(listRelationships).mockResolvedValue(relationships)
    const user = userEvent.setup()

    renderApp()
    await waitFor(() => expect(screen.getByTestId('case-header')).toBeInTheDocument())
    expect(screen.getByTestId('graph-mode-label')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: navLabel }))

    expect(await screen.findByTestId(testId)).toBeInTheDocument()
    // Leaving the graph view unmounts the graph-only workspace.
    expect(screen.queryByTestId('graph-mode-label')).not.toBeInTheDocument()
  })

  it('selecting a component from the sidebar focuses it in the graph', async () => {
    vi.mocked(getCaseOverview).mockResolvedValue(overview)
    vi.mocked(listEntities).mockResolvedValue(entities)
    vi.mocked(listRelationships).mockResolvedValue(relationships)
    const user = userEvent.setup()

    renderApp()
    await waitFor(() => expect(screen.getByTestId('case-header')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Components' }))
    await user.click(await screen.findByRole('button', { name: /Component 1/ }))

    expect(screen.getByTestId('graph-mode-label')).toHaveTextContent('Component 1')
  })
})

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import './App.css'
import { ApiError, getCaseOverview, listEntities, listRelationships } from './api/client'
import type { GraphComponent, ResolvedEntity } from './api/types'
import { CaseHeader } from './components/CaseHeader'
import { ComponentsPanel } from './components/ComponentsPanel'
import { ContradictionsPanel } from './components/ContradictionsPanel'
import { EntityDetail } from './components/EntityDetail'
import { EntityList } from './components/EntityList'
import { ErrorScreen } from './components/ErrorScreen'
import { EvidencePanel } from './components/EvidencePanel'
import { FindingsPanel } from './components/FindingsPanel'
import { GapsPanel } from './components/GapsPanel'
import { PathExplorer } from './components/PathExplorer'
import { RelationshipDetail } from './components/RelationshipDetail'
import { RelationshipList } from './components/RelationshipList'
import { TimelinePanel } from './components/TimelinePanel'
import { GraphPanel, type PathOverlay } from './graph/GraphPanel'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8420'

type TopView = 'graph' | 'evidence' | 'timeline' | 'contradictions' | 'gaps' | 'findings'
type GraphSidebarTab = 'entities' | 'relationships' | 'components'

const TOP_VIEWS: { id: TopView; label: string }[] = [
  { id: 'graph', label: 'Graph' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'contradictions', label: 'Contradictions' },
  { id: 'gaps', label: 'Gaps' },
  { id: 'findings', label: 'Findings' },
]

function App() {
  const [topView, setTopView] = useState<TopView>('graph')
  const [sidebarTab, setSidebarTab] = useState<GraphSidebarTab>('entities')
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null)
  const [selectedRelationshipId, setSelectedRelationshipId] = useState<string | null>(null)
  const [pathOverlay, setPathOverlay] = useState<PathOverlay | null>(null)
  const [focusComponent, setFocusComponent] = useState<GraphComponent | null>(null)
  const [focusComponentEntities, setFocusComponentEntities] = useState<
    Record<string, ResolvedEntity> | undefined
  >(undefined)

  const overviewQuery = useQuery({ queryKey: ['case'], queryFn: getCaseOverview })
  const entitiesQuery = useQuery({
    queryKey: ['entities'],
    queryFn: () => listEntities(),
    enabled: overviewQuery.isSuccess,
  })
  const relationshipsQuery = useQuery({
    queryKey: ['relationships'],
    queryFn: () => listRelationships(),
    enabled: overviewQuery.isSuccess,
  })

  if (overviewQuery.isLoading) {
    return <div className="loading-screen">Connecting to the Witnessgraph API...</div>
  }
  if (overviewQuery.isError) {
    const message =
      overviewQuery.error instanceof ApiError
        ? overviewQuery.error.message
        : 'Could not load the case overview.'
    return <ErrorScreen message={message} apiBaseUrl={API_BASE_URL} />
  }
  if (!overviewQuery.data || !entitiesQuery.data || !relationshipsQuery.data) {
    return <div className="loading-screen">Loading case data...</div>
  }

  function selectEntity(id: string | null) {
    setSelectedEntityId(id)
    setSelectedRelationshipId(null)
  }

  function selectRelationship(id: string | null) {
    setSelectedRelationshipId(id)
    setSelectedEntityId(null)
  }

  function focusComponentAndClearOverlay(
    component: GraphComponent | null,
    entities?: Record<string, ResolvedEntity>,
  ) {
    setFocusComponent(component)
    setFocusComponentEntities(entities)
    setPathOverlay(null)
  }

  const selectedEntity = selectedEntityId
    ? (entitiesQuery.data.find((e) => e.id === selectedEntityId) ?? null)
    : null

  return (
    <div className="app-layout">
      <CaseHeader overview={overviewQuery.data} />
      <nav className="top-nav" aria-label="Case sections">
        {TOP_VIEWS.map((view) => (
          <button
            key={view.id}
            type="button"
            className={topView === view.id ? 'active' : ''}
            aria-current={topView === view.id ? 'page' : undefined}
            onClick={() => setTopView(view.id)}
          >
            {view.label}
          </button>
        ))}
      </nav>

      {topView === 'graph' && (
        <div className="app-body">
          <aside className="sidebar">
            <div className="sidebar-tabs">
              <button
                type="button"
                className={sidebarTab === 'entities' ? 'active' : ''}
                onClick={() => setSidebarTab('entities')}
              >
                Entities
              </button>
              <button
                type="button"
                className={sidebarTab === 'relationships' ? 'active' : ''}
                onClick={() => setSidebarTab('relationships')}
              >
                Relationships
              </button>
              <button
                type="button"
                className={sidebarTab === 'components' ? 'active' : ''}
                onClick={() => setSidebarTab('components')}
              >
                Components
              </button>
            </div>
            {sidebarTab === 'entities' && (
              <EntityList
                entities={entitiesQuery.data}
                selectedEntityId={selectedEntityId}
                onSelect={selectEntity}
              />
            )}
            {sidebarTab === 'relationships' && (
              <RelationshipList
                relationships={relationshipsQuery.data}
                selectedRelationshipId={selectedRelationshipId}
                onSelect={selectRelationship}
              />
            )}
            {sidebarTab === 'components' && (
              <ComponentsPanel
                focusedIndex={focusComponent?.index ?? null}
                onFocus={focusComponentAndClearOverlay}
              />
            )}
          </aside>

          <main className="main-column">
            <GraphPanel
              entities={entitiesQuery.data}
              relationships={relationshipsQuery.data}
              selectedEntityId={selectedEntityId}
              selectedRelationshipId={selectedRelationshipId}
              onSelectEntity={selectEntity}
              onSelectRelationship={selectRelationship}
              pathOverlay={pathOverlay}
              onClearOverlay={() => setPathOverlay(null)}
              focusComponent={focusComponent}
              focusComponentEntities={focusComponentEntities}
              onClearComponent={() => {
                setFocusComponent(null)
                setFocusComponentEntities(undefined)
              }}
            />
            <PathExplorer
              entities={entitiesQuery.data}
              onOverlay={(overlay) => {
                setPathOverlay(overlay)
                setFocusComponent(null)
                setFocusComponentEntities(undefined)
              }}
            />
          </main>

          <aside className="detail-column">
            {selectedEntity && (
              <EntityDetail entity={selectedEntity} onClose={() => selectEntity(null)} />
            )}
            {selectedRelationshipId && (
              <RelationshipDetail
                relationshipId={selectedRelationshipId}
                onClose={() => selectRelationship(null)}
              />
            )}
            {!selectedEntity && !selectedRelationshipId && (
              <p className="empty-note">
                Select an entity or relationship (from a list or the graph) to see its details and
                provenance.
              </p>
            )}
          </aside>
        </div>
      )}

      {topView === 'evidence' && (
        <div className="single-column">
          <EvidencePanel />
        </div>
      )}
      {topView === 'timeline' && (
        <div className="single-column">
          <TimelinePanel />
        </div>
      )}
      {topView === 'contradictions' && (
        <div className="single-column">
          <ContradictionsPanel />
        </div>
      )}
      {topView === 'gaps' && (
        <div className="single-column">
          <GapsPanel />
        </div>
      )}
      {topView === 'findings' && (
        <div className="single-column">
          <FindingsPanel />
        </div>
      )}
    </div>
  )
}

export default App

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import './App.css'
import { getCaseOverview, listEntities, listRelationships } from './api/client'
import { ApiError } from './api/client'
import { CaseHeader } from './components/CaseHeader'
import { ContradictionsPanel } from './components/ContradictionsPanel'
import { EntityDetail } from './components/EntityDetail'
import { EntityList } from './components/EntityList'
import { ErrorScreen } from './components/ErrorScreen'
import { PathExplorer } from './components/PathExplorer'
import { RelationshipDetail } from './components/RelationshipDetail'
import { RelationshipList } from './components/RelationshipList'
import { GraphPanel, type PathOverlay } from './graph/GraphPanel'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8420'

type SidebarTab = 'entities' | 'relationships' | 'contradictions'

function App() {
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null)
  const [selectedRelationshipId, setSelectedRelationshipId] = useState<string | null>(null)
  const [pathOverlay, setPathOverlay] = useState<PathOverlay | null>(null)
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('entities')

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

  const selectedEntity = selectedEntityId
    ? (entitiesQuery.data.find((e) => e.id === selectedEntityId) ?? null)
    : null

  return (
    <div className="app-layout">
      <CaseHeader overview={overviewQuery.data} />
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
              className={sidebarTab === 'contradictions' ? 'active' : ''}
              onClick={() => setSidebarTab('contradictions')}
            >
              Contradictions
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
          {sidebarTab === 'contradictions' && <ContradictionsPanel />}
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
          />
          <PathExplorer entities={entitiesQuery.data} onOverlay={setPathOverlay} />
        </main>

        <aside className="detail-column">
          {selectedEntity && <EntityDetail entity={selectedEntity} onClose={() => selectEntity(null)} />}
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
    </div>
  )
}

export default App

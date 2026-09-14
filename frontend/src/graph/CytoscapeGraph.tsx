// A thin React wrapper around Cytoscape.js core -- deliberately not the
// react-cytoscapejs package (one fewer dependency, and it keeps full,
// direct control over layout determinism; see the architecture's "no
// unnecessary framework complexity" guidance). Cytoscape itself owns all
// node/edge selection, styling, and interaction; this component only
// wires React state in and out of it.

import cytoscape, { type Core, type ElementDefinition, type LayoutOptions, type StylesheetJson } from 'cytoscape'
import { useEffect, useRef } from 'react'

export interface CytoscapeGraphProps {
  elements: ElementDefinition[]
  stylesheet: StylesheetJson
  layout: LayoutOptions
  onSelectNode: (id: string | null) => void
  onSelectEdge: (id: string | null) => void
}

export function CytoscapeGraph({ elements, stylesheet, layout, onSelectNode, onSelectEdge }: CytoscapeGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<Core | null>(null)

  // Create the Cytoscape instance once.
  useEffect(() => {
    if (!containerRef.current) return
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: stylesheet,
      layout: { name: 'preset' },
      wheelSensitivity: 0.2,
    })
    cy.on('tap', 'node', (evt) => {
      onSelectNode(evt.target.id())
    })
    cy.on('tap', 'edge', (evt) => {
      onSelectEdge(evt.target.id())
    })
    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        onSelectNode(null)
        onSelectEdge(null)
      }
    })
    cyRef.current = cy
    return () => {
      cy.destroy()
      cyRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keep the stylesheet current without rebuilding the graph.
  useEffect(() => {
    cyRef.current?.style(stylesheet)
  }, [stylesheet])

  // Replace elements and re-run the (deterministic) layout whenever the
  // data changes.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().remove()
    cy.add(elements)
    cy.layout(layout).run()
  }, [elements, layout])

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} data-testid="cytoscape-container" />
}

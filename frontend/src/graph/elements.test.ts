import { describe, expect, it } from 'vitest'
import type { Entity, NeighborsResult, Relationship, TraversalStep } from '../api/types'
import { displayLabel, egoNetworkElements, fullGraphElements, pathOverlayElements, withHighlightClasses } from './elements'

function entity(id: string, entity_type: string, identifiers: Record<string, string> = {}): Entity {
  return { id, entity_type, identifiers, first_seen: null, last_seen: null, derived_from: ['ev-1'] }
}

function relationship(id: string, source: string, target: string): Relationship {
  return {
    id,
    relationship_type: 'connected_to',
    source_entity_id: source,
    target_entity_id: target,
    attributes: {},
    derived_from: ['ev-1'],
  }
}

function step(rel: Relationship, from: string, to: string): TraversalStep {
  return { from_entity_id: from, to_entity_id: to, walked_direction: 'forward', relationship: rel }
}

describe('displayLabel', () => {
  it('prefers a conventional identifier key when present', () => {
    expect(displayLabel(entity('e-1', 'host', { hostname: 'web01', other: 'x' }))).toBe('host: web01')
  })

  it('falls back to a truncated id when there are no identifiers', () => {
    expect(displayLabel(entity('entity-abcdefgh12345', 'host'))).toBe('host:entity-a')
  })
})

describe('fullGraphElements', () => {
  it('produces one element per entity and relationship, sorted by id', () => {
    const entities = [entity('e-b', 'host'), entity('e-a', 'user')]
    const relationships = [relationship('r-1', 'e-a', 'e-b')]
    const elements = fullGraphElements(entities, relationships)
    const ids = elements.map((el) => el.data.id)
    expect(ids).toEqual(['e-a', 'e-b', 'r-1'])
  })
})

describe('egoNetworkElements', () => {
  it('uses the resolved entities map for real type/identifiers, never a placeholder', () => {
    const rel = relationship('r-1', 'e-a', 'e-b')
    const result: NeighborsResult = {
      origin_entity_id: 'e-a',
      direction: 'out',
      max_depth: 1,
      reached: [{ entity_id: 'e-b', hop_count: 1, via: step(rel, 'e-a', 'e-b') }],
      entities: {
        'e-a': { entity_id: 'e-a', found: true, entity_type: 'host', identifiers: { hostname: 'a' } },
        'e-b': { entity_id: 'e-b', found: true, entity_type: 'host', identifiers: { hostname: 'b' } },
      },
    }
    const elements = egoNetworkElements(result)
    const originNode = elements.find((el) => el.data.id === 'e-a')
    expect(originNode?.data.entity_type).toBe('host')
    expect(originNode?.data.label).toBe('host: a')
  })
})

describe('pathOverlayElements', () => {
  it('assigns a distinct chain class per chain and merges classes for a shared edge', () => {
    const sharedRel = relationship('r-shared', 'e-a', 'e-d')
    const chainA = [step(sharedRel, 'e-a', 'e-d')]
    const otherRel = relationship('r-other', 'e-a', 'e-d')
    const chainB = [step(otherRel, 'e-a', 'e-d')]
    const { elements, edgeChainClasses } = pathOverlayElements([chainA, chainB], undefined)
    expect(edgeChainClasses['r-shared']).toEqual(['path-chain-0'])
    expect(edgeChainClasses['r-other']).toEqual(['path-chain-1'])
    expect(elements.map((el) => el.data.id)).toContain('r-shared')
  })
})

describe('withHighlightClasses', () => {
  it('adds wg-selected without discarding an existing class', () => {
    const elements = fullGraphElements([entity('e-a', 'host')], [])
    const [styled] = withHighlightClasses(elements, { selectedId: 'e-a' })
    expect(styled.classes).toContain('wg-selected')
    expect(styled.classes).toContain('entity-type-host')
  })

  it('merges per-edge chain classes onto matching elements', () => {
    const elements = fullGraphElements([], [relationship('r-1', 'e-a', 'e-b')])
    const [styled] = withHighlightClasses(elements, { edgeChainClasses: { 'r-1': ['path-chain-0'] } })
    expect(styled.classes).toContain('path-chain-0')
  })
})

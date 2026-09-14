import type { StylesheetJson } from 'cytoscape'
import { PATH_CHAIN_COLORS } from './elements'

/** Base "context" styling plus the analytical-overlay classes
 * (`.path-chain-N`) and the "currently open in the detail panel"
 * selection styling (`.wg-selected`) -- kept visually and semantically
 * distinct, per §7's "clear distinction between the selected graph
 * context and analytical overlays". */
export const baseStylesheet: StylesheetJson = [
  {
    selector: 'node',
    style: {
      'background-color': '#8892a0',
      label: 'data(label)',
      color: '#1a1a1a',
      'font-size': 10,
      'text-valign': 'bottom',
      'text-margin-y': 4,
      width: 28,
      height: 28,
      'border-width': 0,
    },
  },
  {
    selector: 'edge',
    style: {
      width: 1.5,
      'line-color': '#c3c9d1',
      'target-arrow-color': '#c3c9d1',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      label: 'data(label)',
      'font-size': 8,
      color: '#5a6270',
      'text-rotation': 'autorotate',
    },
  },
  {
    selector: '.wg-selected',
    style: {
      'border-width': 3,
      'border-color': '#f2c744',
      'line-color': '#f2c744',
      'target-arrow-color': '#f2c744',
      width: 3,
    },
  },
  ...PATH_CHAIN_COLORS.map((color, index) => ({
    selector: `.path-chain-${index}`,
    style: {
      'line-color': color,
      'target-arrow-color': color,
      'background-color': color,
      width: 4,
    },
  })),
]

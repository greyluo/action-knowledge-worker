# 3D Ontology View — Design Spec

**Date:** 2026-04-21  
**Status:** Approved

## Overview

Add a 3D explore mode to the existing OntologyView. The current 2D SVG force graph stays unchanged and remains the primary editing surface. A `[2D | 3D]` toggle in the header switches to a read-only 3D view for visually exploring graph structure.

## Goals

- Let users rotate and zoom the ontology graph in 3D to see cluster structure that is hard to read in a flat 2D layout
- Keep the existing 2D editing workflow completely intact — no regressions
- Use z-axis depth to visually separate entity types (Person / Company / Deal etc. at distinct depth rings)
- Clicking a node in 3D opens the existing detail panel in read-only mode

## Non-Goals

- No editing in 3D mode (create, delete, or modify entities/edges)
- No full-screen overlay — 3D replaces the canvas in-place, sidebar stays visible
- No custom shaders, bloom, or post-processing effects

## Library

**`react-force-graph`** — React wrapper around `3d-force-graph` (Three.js + d3-force-3d). Chosen because:
- Shares the same force physics semantics as the existing `d3-force` layout
- Minimal API surface for the use case (node/link data in, 3D canvas out)
- Adds ~200KB to the bundle, acceptable for a dev tool
- `ForceGraph3D` component handles orbit controls, zoom, and WebGL context lifecycle

## Architecture

### New: `Graph3DCanvas` component

Lives in `OntologyView.tsx` alongside the existing `GraphCanvas`. Props are a subset of `GraphCanvasProps`:

```ts
interface Graph3DCanvasProps {
  entities: Entity[]
  edges: Edge[]
  selectedId: string | null
  width: number
  height: number
  onSelect: (id: string | null) => void
}
```

Responsibilities:
- Converts `Entity[]` / `Edge[]` into `{ nodes, links }` objects for `ForceGraph3D`
- Applies a custom z-force after mount: each entity type maps to a fixed z-band (step of 120 units). The force pulls nodes toward their type's target z, strength 0.8.
- Node color: reuses the existing `typeColor()` helper
- Node label: entity name, rendered via `nodeLabel`
- `onNodeClick`: calls `onSelect(node.id)`, or `onSelect(null)` when clicking the background
- Background: dark (`#0d0d1a`) to make the depth rings legible

**Z-band assignment:** types are sorted alphabetically and assigned z-positions `[0, 120, 240, …]`. This is deterministic and requires no configuration.

### Modified: `OntologyView`

Adds `viewMode: '2d' | '3d'` state (default `'2d'`).

Header changes:
- A segmented `[2D | 3D]` toggle button, placed between the entity-count stats and the `+ Entity` button
- `+ Entity` button is `disabled` and visually dimmed when `viewMode === '3d'`

Body changes:
- Renders `Graph3DCanvas` when `viewMode === '3d'`, `GraphCanvas` when `'2d'`
- `selectedId` is preserved across mode switches so the detail panel stays open when toggling
- `isAddingEntity` is reset to `false` when switching to 3D

### Modified: `DetailPanel`

Adds `readOnly?: boolean` prop.

When `readOnly={true}`:
- The Edit button is hidden
- The Delete / confirm-delete flow is hidden
- The Add Edge button is hidden
- A small note replaces the action buttons: `"read-only in 3D mode"`
- All existing display logic (properties, connections list) is unchanged

## Data Flow

```
OntologyView
  viewMode='3d'
  ├── Graph3DCanvas ─ onNodeClick → setSelectedId
  └── DetailPanel(readOnly=true) ← selectedId
```

## Toggle UI

```
[ 2D | 3D ]  ← segmented control, styled like existing btnBase
              Active segment uses btnPrimary style
              Inactive segment uses btnBase style
```

No icon — the text labels are self-explanatory.

## Footer

In 3D mode the footer legend updates its hint text:
- 2D: `Click node for details · Drag · Scroll to zoom`
- 3D: `Click node for details · Drag to rotate · Scroll to zoom`

The stored/derived edge legend stays visible in both modes.

## File Changes

| File | Change |
|------|--------|
| `frontend/package.json` | Add `react-force-graph` dependency |
| `frontend/src/components/ontology/OntologyView.tsx` | New `Graph3DCanvas` component; modify `OntologyView` (toggle state, conditional render); modify `DetailPanel` (readOnly prop) |

No new files required — everything fits in the existing `OntologyView.tsx`.

## Open Questions

None — all design decisions resolved during brainstorming.

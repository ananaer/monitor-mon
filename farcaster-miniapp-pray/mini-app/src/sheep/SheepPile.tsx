/**
 * Layered board renderer.
 * - Tiles are absolutely positioned within each column.
 * - Selectable if no higher-layer tile overlaps the same (col,row).
 */

import { computeSelectableTiles, jitterForId, type Column, type SheepTile } from "./logic";
import { SheepTileView } from "./SheepTileView";

const GRID_X = 52; // Horizontal step
const GRID_Y = 44; // Vertical step
const LAYER_OFFSET_Y = 6; // Slight vertical lift for layers

type Props = {
  columns: Column[];
  onSelect: (tile: SheepTile) => void;
};

export function SheepPile({ columns, onSelect }: Props) {
  const selectable = new Set(computeSelectableTiles(columns).map((t) => t.id));

  // Determine board width to center it
  const numCols = columns.length;
  const boardWidth = numCols * GRID_X;

  // Calculate rendering logic
  const allTiles = columns.flatMap(col => col.map(t => ({ ...t })));

  return (
    <div
      className="sheep-pile"
      style={{
        width: boardWidth,
        minHeight: 400,
        margin: "0 auto"  // Center the pile container
      }}
    >
      {allTiles.map((tile) => {
        const isSelectable = selectable.has(tile.id);
        const jitterX = jitterForId(tile.id, 2);
        const jitterY = jitterForId(tile.id + "y", 2);

        // Grid Position
        const x = tile.col * GRID_X + jitterX;
        const y = tile.row * GRID_Y - (tile.layer * LAYER_OFFSET_Y) + jitterY;

        return (
          <div
            key={tile.id}
            className="sheep-tile-wrap"
            style={{
              position: "absolute",
              top: y,
              left: x,
              zIndex: 10 + tile.layer + tile.row, // Better z-indexing: lower rows should be on top for 2.5D look? Actually default layer sort is safer.
              // Let's rely on logic.ts sort (layer asc) + explicit zIndex from style
            }}
          >
            {/* Pass style overriding position to the component if needed, or wrap it */}
            <SheepTileView
              tile={tile}
              selectable={isSelectable}
              onSelect={onSelect}
            />
          </div>
        );
      })}
    </div>
  );
}

export default SheepPile;

import type { SheepTile } from "./logic";

type Props = {
  tile: SheepTile;
  selectable: boolean;
  onSelect: (tile: SheepTile) => void;
};

// Map current emoji set to sprite sheet indices
const TILE_MAP: Record<string, number> = {
  "🐑": 0, "🐱": 1, "🐶": 2, "🐷": 3,
  "🐔": 4, "🐸": 5, "🐙": 6, "🐝": 7,
  "🐠": 8, "🌽": 9, "🥕": 10, "🍅": 11,
  "🍆": 12, "🥑": 13, "🍄": 14, "🍇": 15
};

export function SheepTileView({ tile, selectable, onSelect }: Props) {
  // Sprite sheet calculation: 4x4 grid
  const index = TILE_MAP[tile.type] ?? 0;
  const col = index % 4;
  const row = Math.floor(index / 4);
  const bgX = col * (100 / 3);
  const bgY = row * (100 / 3);

  return (
    <button
      type="button"
      className={`sheep-tile ${selectable ? "sheep-tile--selectable" : "sheep-tile--blocked"}`}
      onClick={() => selectable && onSelect(tile)}
      disabled={!selectable}
      aria-pressed={false}
      title={selectable ? "可选" : "被覆盖"}
      style={{
        zIndex: tile.layer * 10, // Ensure visual stacking order
      }}
    >
      <div
        className="tile-inner"
      >
        {/* Highlight overlay for blocked tiles */}
        {!selectable && <div className="tile-overlay" />}

        {/* Sprite Image */}
        <div
          className="tile-sprite"
          style={{
            backgroundImage: "url(/assets/sheep/tiles.png)",
            backgroundPosition: `${bgX}% ${bgY}%`,
            // filter: selectable ? "contrast(1.05) saturate(1.1)" : "grayscale(0.5)", // Let natural clay texture shine
            filter: selectable ? "none" : "grayscale(0.6) brightness(0.9)",
          }}
        />
      </div>
    </button>
  );
}

export default SheepTileView;

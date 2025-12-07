/**
 * Core logic for a "Sheep a Sheep" stack + buffer game.
 * Layered model: multiple tiles can share the same (col,row) but different layer.
 * A tile is selectable only if no higher-layer tile overlaps the same (col,row).
 */

export type SheepTile = {
  id: string;
  type: string;
  col: number;
  row: number;
  layer: number;
};

export type Column = SheepTile[];

export type GameOptions = {
  columns: number;
  minRows: number;
  maxRows: number;
  maxStackHeight: number;
  tileSet: string[];
  seed?: number;
};

export type BufferEntry = SheepTile;

export type BufferResolveResult = {
  buffer: BufferEntry[];
  cleared: number;
  clearedTriples: number;
};

export function generateColumns(options: GameOptions): Column[] {
  const rng = createRng(options.seed ?? Date.now());

  // Retry loop to ensure valid topology
  for (let attempt = 0; attempt < 100; attempt++) {
    const columns = tryGenerateSolvableLevel(options, rng);
    if (columns) {
      return columns;
    }
  }

  // Fallback (extremely rare): return a random one if solvable gen fails repeatedly
  // Ideally this should not happen with reasonable params.
  console.warn("Failed to generate solvable level after 100 attempts, falling back to random.");
  return generateRandomColumns(options, rng);
}

// Internal helper for old random logic (fallback)
function generateRandomColumns(options: GameOptions, rng: Rng): Column[] {
  // ... simplified version of previous logic just for fallback ...
  // For now, let's just perform the topology generation and random fill
  // Re-implementing simplified version to save space/complexity as fallback
  const plans = generateTopology(options, rng);
  const totalTiles = plans.flat().reduce((a, b) => a + b, 0);
  const pool = buildTilePool(totalTiles, options.tileSet, rng);
  return fillTopology(plans, pool, options.columns);
}

function tryGenerateSolvableLevel(options: GameOptions, rng: Rng): Column[] | null {
  // 1. Generate Topology
  const plans = generateTopology(options, rng);
  const totalTiles = plans.flat().reduce((a, b) => a + b, 0);

  if (totalTiles % 3 !== 0) return null; // Should be handled by generateTopology logic

  // 2. Create Empty Board State
  // We need to track which tiles are "solved" (removed) to simulate valid moves
  type SimTile = { id: string; col: number; row: number; layer: number; type: string | null };
  const allTiles: SimTile[] = [];

  // Build structure
  let cursor = 0;
  for (let col = 0; col < options.columns; col++) {
    const heights = plans[col];
    for (let row = 0; row < heights.length; row++) {
      for (let layer = 0; layer < heights[row]; layer++) {
        allTiles.push({
          id: `c${col}-r${row}-l${layer}`, // temporary ID
          col, row, layer, type: null
        });
        cursor++;
      }
    }
  }

  // 3. Constructive Assignment (Reverse Solver)
  // repeatedly pick 3 selectable tiles and assign them the same type
  const solvedIndices = new Set<number>(); // Indices in allTiles that are "removed"

  // Helper to check selectability given current solved state
  const isSelectableSim = (targetIdx: number) => {
    const target = allTiles[targetIdx];
    // A tile is selectable if no UNSOLVED tile is above it
    // Check all potentially blocking tiles
    for (let i = 0; i < allTiles.length; i++) {
      if (solvedIndices.has(i)) continue; // Ignored solved tiles
      const other = allTiles[i];
      if (other.col === target.col && other.row === target.row && other.layer > target.layer) {
        return false;
      }
    }
    return true;
  };

  while (solvedIndices.size < allTiles.length) {
    // Find candidates
    const candidates: number[] = [];
    for (let i = 0; i < allTiles.length; i++) {
      if (!solvedIndices.has(i) && isSelectableSim(i)) {
        candidates.push(i);
      }
    }

    if (candidates.length < 3) {
      return null; // Dead end, topology restricts valid triplets
    }

    // Pick 3 random candidates
    const group: number[] = [];
    const available = [...candidates];

    for (let k = 0; k < 3; k++) {
      const pickIdx = Math.floor(rng() * available.length);
      const pickedTileIdx = available[pickIdx];
      group.push(pickedTileIdx);
      // Remove from available local array so we don't pick same one
      available.splice(pickIdx, 1);
    }

    // "Remove" them from board (add to solved)
    group.forEach(idx => solvedIndices.add(idx));

    // Determine type for this triplet
    // We can assign types later or now. Let's record the grouping.
    // For simplicity, just pick a random type now.
    const type = options.tileSet[Math.floor(rng() * options.tileSet.length)];
    group.forEach(idx => {
      allTiles[idx].type = type;
    });
  }

  // 4. Convert back to Column format
  const columns: Column[] = Array.from({ length: options.columns }, () => []);

  // Re-sort tiles into their columns
  // Note: logic.ts usually creates IDs with index at the end. We reconstruct proper IDs.
  // We need to output them in order.

  // Group by column
  const colsData: SimTile[][] = Array.from({ length: options.columns }, () => []);
  allTiles.forEach(t => colsData[t.col].push(t));

  for (let c = 0; c < options.columns; c++) {
    // Sort logic requires us to return tiles in specific order? 
    // Usually logic.ts handles flattening, but valid Column is just array of SheepTile.
    // Let's ensure they are sorted by layer for consistency, though UI handles absolute pos.
    colsData[c].sort((a, b) => a.layer - b.layer); // low layer first? or standard order?

    // Re-assign IDs to match standard format if needed, or just keep unique.
    // Standard format: `c${col}-r${row}-l${layer}-${cursor}`
    // We'll regenerate cursor based unique IDs
    colsData[c].forEach((t, i) => {
      columns[c].push({
        id: `${t.id}-${c * 1000 + i}`, // Ensure unique
        col: t.col,
        row: t.row,
        layer: t.layer,
        type: t.type!
      });
    });
  }

  return columns;
}

function generateTopology(options: GameOptions, rng: Rng): number[][] {
  const plans: number[][] = [];
  let totalTiles = 0;

  for (let col = 0; col < options.columns; col += 1) {
    const rows = randomInt(rng, options.minRows, options.maxRows);
    const heights: number[] = [];
    for (let row = 0; row < rows; row += 1) {
      const stackHeight = randomInt(rng, 1, options.maxStackHeight);
      heights.push(stackHeight);
      totalTiles += stackHeight;
    }
    plans.push(heights);
  }

  // Ensure total tiles is a multiple of 3
  const remainder = totalTiles % 3;
  if (remainder !== 0) {
    const extra = 3 - remainder;
    const last = plans[plans.length - 1] ?? [];
    if (last.length === 0) {
      last.push(extra);
    } else {
      last[last.length - 1] += extra;
    }
    plans[plans.length - 1] = last;
  }

  return plans;
}

function fillTopology(plans: number[][], pool: string[], numCols: number): Column[] {
  const columns: Column[] = [];
  let cursor = 0;

  for (let col = 0; col < numCols; col += 1) {
    const heights = plans[col] ?? [];
    const tiles: SheepTile[] = [];
    for (let row = 0; row < heights.length; row += 1) {
      const stackHeight = heights[row];
      for (let layer = 0; layer < stackHeight; layer += 1) {
        const type = pool[cursor % pool.length];
        tiles.push({
          id: `c${col}-r${row}-l${layer}-${cursor}`,
          type,
          col,
          row,
          layer,
        });
        cursor += 1;
      }
    }
    tiles.sort((a, b) => a.layer - b.layer);
    columns.push(tiles);
  }
  return columns;
}

export function flattenColumns(columns: Column[]): SheepTile[] {
  return columns.flat();
}

export function isTileSelectable(tile: SheepTile, columns: Column[]): boolean {
  const tiles = flattenColumns(columns);
  return !tiles.some(
    (other) =>
      other.id !== tile.id &&
      other.col === tile.col &&
      other.row === tile.row &&
      other.layer > tile.layer,
  );
}

export function computeSelectableTiles(columns: Column[]): SheepTile[] {
  const tiles = flattenColumns(columns);
  return tiles.filter((tile) => isTileSelectable(tile, columns));
}

export function takeTileIfSelectable(columns: Column[], tileId: string) {
  const tiles = flattenColumns(columns);
  const target = tiles.find((t) => t.id === tileId);
  if (!target || !isTileSelectable(target, columns)) {
    return { ok: false as const };
  }

  const nextColumns = columns.map((col) => col.filter((t) => t.id !== tileId));
  return { ok: true as const, tile: target, columns: nextColumns };
}

// Deterministic jitter for visual staggering
export function jitterForId(id: string, range: number): number {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return ((hash % (range * 2 + 1)) - range) / 1;
}

export function resolveBuffer(buffer: BufferEntry[]): BufferResolveResult {
  const typeIndices: Record<string, number[]> = {};
  buffer.forEach((entry, idx) => {
    typeIndices[entry.type] = typeIndices[entry.type] ?? [];
    typeIndices[entry.type].push(idx);
  });

  const removeIndices = new Set<number>();
  Object.entries(typeIndices).forEach(([type, indices]) => {
    const tripleCount = Math.floor(indices.length / 3);
    if (tripleCount === 0) return;
    const toRemove = tripleCount * 3;
    for (let i = 0; i < toRemove; i += 1) {
      removeIndices.add(indices[i]);
    }
  });

  if (removeIndices.size === 0) {
    return { buffer, cleared: 0, clearedTriples: 0 };
  }

  const nextBuffer = buffer.filter((_, idx) => !removeIndices.has(idx));
  const cleared = removeIndices.size;
  return { buffer: nextBuffer, cleared, clearedTriples: cleared / 3 };
}

export function isBoardEmpty(columns: Column[]): boolean {
  return columns.every((col) => col.length === 0);
}

export function isBufferFail(buffer: BufferEntry[], slotLimit: number): boolean {
  return buffer.length >= slotLimit;
}

// ---------- helpers ----------

type Rng = () => number;

function createRng(seed: number): Rng {
  let t = seed + 0x6d2b79f5;
  return () => {
    t += 0x6d2b79f5;
    let x = t;
    x = Math.imul(x ^ (x >>> 15), 1 | x);
    x ^= x + Math.imul(x ^ (x >>> 7), 61 | x);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

function randomInt(rng: Rng, min: number, max: number): number {
  return Math.floor(rng() * (max - min + 1)) + min;
}

function buildTilePool(total: number, tileSet: string[], rng: Rng): string[] {
  const pool: string[] = [];
  for (let i = 0; i < total; i += 1) {
    pool.push(tileSet[i % tileSet.length]);
  }
  shuffle(pool, rng);
  return pool;
}

function shuffle<T>(items: T[], rng: Rng): void {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
}

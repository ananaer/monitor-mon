/**
 * 羊了个羊（堆叠 + 7 槽三消）克隆页面。
 * 用法：在 App 中渲染 <SheepGamePage />；项目仍通过 `npm run dev` 运行。
 * 规则：
 * - 仅可点击未被覆盖的牌（同 col/row 上 layer 最大者）；点击后放入 7 槽缓冲区。
 * - 缓冲区内任意三张同类型立即消除。
 * - 缓冲区满且无可消除则失败；所有牌清空即胜利。
 * 存档：
 * - localStorage 键 "sheep-stats" 记录 bestMoves、totalClears、attempts、lastPlay。
 * UI：
 * - 分层可视化、柔和按钮组、动画（点击压缩/消除闪烁/失败抖动）、轻量音效（Web Audio）。
 */

import { useEffect, useState } from "react";

import { SheepBuffer } from "./SheepBuffer";
import SheepOverlay from "./SheepOverlay";
import SheepPile from "./SheepPile";
import {
  generateColumns,
  isBoardEmpty,
  isBufferFail,
  resolveBuffer,
  takeTileIfSelectable,
  type BufferEntry,
  type Column,
  type GameOptions,
  type SheepTile,
} from "./logic";
import { loadSheepStats, recordSheepResult, type SheepStats } from "./storage";
import useSoundEffects from "./useSoundEffects";

const TILE_SET = ["🐑", "🐱", "🐶", "🐷", "🐔", "🐸", "🐙", "🐝", "🐠", "🌽", "🥕", "🍅", "🍆", "🥑", "🍄", "🍇"];

// Difficulty adjustment: Use a subset of tiles for the start
// Difficulty adjustment: Use a subset of tiles for the start
const ACTIVE_TILE_SET = TILE_SET.slice(0, 7); // Only first 7 types

function getOptionsForLevel(level: number, seed: number): GameOptions {
  if (level === 1) {
    // Tutorial Level: TINY board, < 10 tiles (aim for 9)
    // 3 columns, 3 rows, 1 layer stack = 9 tiles total.
    return {
      columns: 3,
      minRows: 3,
      maxRows: 3,
      maxStackHeight: 1,
      tileSet: ACTIVE_TILE_SET.slice(0, 3), // Only 3 types for matching
      seed
    };
  }

  // Level 2+: Standard "Easy" difficulty
  return {
    columns: 6,
    minRows: 3,
    maxRows: 5,
    maxStackHeight: 2,
    tileSet: ACTIVE_TILE_SET,
    seed
  };
}

const SLOT_LIMIT = 7;

type Status = "playing" | "win" | "lose";

export function SheepGamePage() {
  const [level, setLevel] = useState(1);
  const [seed, setSeed] = useState(() => Date.now());

  // Hydrate columns based on current level and seed
  const [columns, setColumns] = useState<Column[]>(() =>
    generateColumns(getOptionsForLevel(1, Date.now()))
  );

  const [buffer, setBuffer] = useState<BufferEntry[]>([]);
  const [status, setStatus] = useState<Status>("playing");
  const [moves, setMoves] = useState(0);
  const [clearedTriples, setClearedTriples] = useState(0);
  const [stats, setStats] = useState<SheepStats>(() => loadSheepStats());
  const [pulseKey, setPulseKey] = useState(0);
  const sound = useSoundEffects();

  useEffect(() => {
    setStats(loadSheepStats());
  }, []);

  useEffect(() => {
    if (status === "playing") return;
    setStats(recordSheepResult(moves, clearedTriples));
  }, [status, moves, clearedTriples]);

  const startGame = (lvl: number, newSeed: number) => {
    setSeed(newSeed);
    setLevel(lvl);
    setColumns(generateColumns(getOptionsForLevel(lvl, newSeed)));
    setBuffer([]);
    setStatus("playing");
    setMoves(0);
    setClearedTriples(0);
  };

  const restart = () => startGame(level, seed); // Retry current
  const newGame = () => startGame(1, Date.now()); // Reset to Level 1
  const nextLevel = () => {
    sound.play("win"); // bonus sound?
    startGame(level + 1, Date.now());
  };

  const handleSelect = (tile: SheepTile) => {
    if (status !== "playing") return;
    sound.play("click");
    const taken = takeTileIfSelectable(columns, tile.id);
    if (!taken.ok) return;

    const nextBufferPre = [...buffer, taken.tile];
    const resolved = resolveBuffer(nextBufferPre);
    const nextMoves = moves + 1;

    setColumns(taken.columns);
    setBuffer(resolved.buffer);
    setMoves(nextMoves);
    if (resolved.clearedTriples > 0) {
      setClearedTriples((prev) => prev + resolved.clearedTriples);
      setPulseKey(Date.now());
      sound.play("eliminate");
    }

    const boardEmpty = isBoardEmpty(taken.columns);
    const bufferEmpty = resolved.buffer.length === 0;
    if (boardEmpty) {
      if (bufferEmpty) {
        sound.play("win");
      } else {
        sound.play("fail");
      }
      setStatus(bufferEmpty ? "win" : "lose");
      return;
    }

    if (isBufferFail(resolved.buffer, SLOT_LIMIT)) {
      sound.play("fail");
      setStatus("lose");
      return;
    }
  };

  return (
    <section className="page">
      <div className="game-bg" style={{ backgroundImage: "url(/assets/sheep/bg_forest.png)" }} />

      <div className="game-header">
        <h2 className="header-title">Match 3 tiles!</h2>
        <div className="chip">Level {level}</div>
      </div>

      <SheepOverlay
        status={status}
        moves={moves}
        clearedTriples={clearedTriples}
        level={level}
        onRestart={restart}
        onNewGame={newGame}
        onNextLevel={nextLevel}
      />

      <div className="game-board">
        <SheepPile columns={columns} onSelect={handleSelect} />
      </div>

      <div className="game-footer">
        <div className="buffer-panel">
          <SheepBuffer buffer={buffer} slotLimit={SLOT_LIMIT} pulseKey={pulseKey} isFailing={status === "lose"} />
        </div>
      </div>
    </section>
  );
}

export default SheepGamePage;

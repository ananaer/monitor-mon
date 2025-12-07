/**
 * HUD overlay with status, score, moves, and restart controls.
 */

type Props = {
  status: "playing" | "win" | "lose";
  moves: number;
  clearedTriples: number;
  level: number;
  onRestart: () => void;
  onNewGame: () => void;
  onNextLevel: () => void;
};

export function SheepOverlay({ status, moves, clearedTriples, level, onRestart, onNewGame, onNextLevel }: Props) {
  const isGameOver = status === "win" || status === "lose";

  // HUD for playing state
  if (!isGameOver) {
    return (
      <div className="sheep-hud">
        <div className="chip-row">
          {/* Minimal HUD */}
          <span className="chip">Level {level}</span>
          <span className="chip">Moves: {moves}</span>
        </div>
      </div>
    );
  }

  // Modal for Game Over state
  return (
    <div className="sheep-modal-overlay">
      <div className="sheep-modal">
        <div className="modal-header">
          {status === "win" ? "🎉 Victory!" : "😭 Game Over"}
        </div>

        <div className="modal-content">
          <p>
            {status === "win"
              ? "Level Complete! Ready for the next challenge?"
              : "No more moves possible!"}
          </p>
          <div className="stat-grid">
            <div className="stat-item">
              <div className="stat-label">Moves</div>
              <div className="stat-val">{moves}</div>
            </div>
            <div className="stat-item">
              <div className="stat-label">Cleared</div>
              <div className="stat-val">{clearedTriples}</div>
            </div>
          </div>
        </div>

        <div className="modal-actions">
          {status === "win" ? (
            <button type="button" className="btn btn--primary btn--large" onClick={onNextLevel}>
              Next Level ➡
            </button>
          ) : (
            <button type="button" className="btn btn--primary btn--large" onClick={onRestart}>
              Try Again 🔄
            </button>
          )}

          <button type="button" className="btn btn--secondary" onClick={onNewGame}>
            Restart Game (Lvl 1)
          </button>
        </div>
      </div>
    </div>
  );
}

export default SheepOverlay;

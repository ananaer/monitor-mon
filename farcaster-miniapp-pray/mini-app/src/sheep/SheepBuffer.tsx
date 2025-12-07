import type { BufferEntry } from "./logic";
import { SheepTileView } from "./SheepTileView";

type Props = {
  buffer: BufferEntry[];
  slotLimit: number;
  pulseKey?: number;
  isFailing?: boolean;
};

export function SheepBuffer({ buffer, slotLimit, pulseKey, isFailing }: Props) {
  const slots = Array.from({ length: slotLimit }, (_, idx) => buffer[idx] ?? null);

  return (
    <div className={`sheep-buffer ${isFailing ? "anim-shake" : ""}`} data-pulse={pulseKey}>
      {slots.map((entry, idx) => {
        const pulseClass = pulseKey ? "anim-pop" : "";
        const key = `${idx}-${entry ? entry.id : 'empty'}`;

        return (
          <div key={key} className={`buffer-slot ${pulseClass}`}>
            {entry ? (
              <div className="pointer-events-none transform scale-90">
                {/* Scale down slightly to fit nicely */}
                <SheepTileView
                  tile={entry}
                  selectable={true} /* Always look "active" in buffer */
                  onSelect={() => { }} /* No interaction in buffer */
                />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export default SheepBuffer;

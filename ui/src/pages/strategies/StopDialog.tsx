import { useState } from "react";
import { useStopStrategy } from "../../api/queries";
import { Dialog } from "../../components/Dialog";

/** Stop asks first (grilling decision 15): it closes every open leg at the market. */
export function StopDialog({
  strategy,
  onClose,
  onDone,
}: {
  strategy: { strategy_id: string; name: string; legs: number } | null;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const stop = useStopStrategy();
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog open={strategy !== null} onClose={onClose} title={`Stop ${strategy?.name ?? ""}?`}>
      <p className="note" style={{ margin: 0 }}>
        Its open legs close at the market and the run ends. It can be started again; a schedule
        stays on.
      </p>
      {error && (
        <div className="error-line" role="alert">
          {error}
        </div>
      )}
      <div className="flex items-center gap-2">
        <span className="flex-1" />
        <button type="button" className="btn" data-variant="ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          data-variant="solid"
          data-autofocus
          disabled={stop.isPending}
          onClick={async () => {
            if (!strategy) return;
            setError(null);
            try {
              await stop.mutateAsync(strategy.strategy_id);
              onDone(`Stopping ${strategy.name}: its legs close within a second.`);
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          {stop.isPending ? "Stopping…" : "Stop strategy"}
        </button>
      </div>
    </Dialog>
  );
}

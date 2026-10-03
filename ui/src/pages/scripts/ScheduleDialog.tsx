import { useState } from "react";
import { type Script, useScheduleScript } from "../../api/queries";
import { Dialog } from "../../components/Dialog";
import { useActions } from "../../shell/actions";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/**
 * When the daemon runs a script by itself (ADR 25): from a start time on
 * chosen weekdays the exchange trades, until a stop time or until it exits.
 */
export function ScheduleDialog({
  script,
  open,
  onClose,
}: {
  script: Script;
  open: boolean;
  onClose: () => void;
}) {
  const current = script.schedule;
  const [start, setStart] = useState(current?.start_time.slice(0, 5) ?? "09:15");
  const [stop, setStop] = useState(current?.stop_time?.slice(0, 5) ?? "");
  const [days, setDays] = useState<number[]>(current?.weekdays ?? [0, 1, 2, 3, 4]);
  const [error, setError] = useState<string | null>(null);
  const save = useScheduleScript();
  const { notify } = useActions();

  const submit = async (off: boolean) => {
    setError(null);
    if (!off && days.length === 0) {
      setError("Pick at least one day.");
      return;
    }
    if (!off && stop && stop <= start) {
      setError("The stop time must be after the start time.");
      return;
    }
    try {
      await save.mutateAsync({
        id: script.script_id,
        schedule: off
          ? null
          : {
              start_time: start,
              stop_time: stop || null,
              weekdays: [...days].sort(),
              exchange: current?.exchange ?? "NSE",
            },
      });
      onClose();
      notify(
        off ? `${script.name} runs only when started now.` : `${script.name}'s schedule saved.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title={`Schedule ${script.name}`}>
      <p className="note" style={{ margin: 0 }}>
        OpenTicker starts it at the start time on each day you pick that the exchange trades, and
        stops it at the stop time, whoever started it. Without a stop time it runs until it exits.
      </p>
      <div className="fields">
        <label className="field">
          <span className="label">Start</span>
          <input
            className="input"
            type="time"
            value={start}
            required
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="label">Stop (optional)</span>
          <input
            className="input"
            type="time"
            value={stop}
            onChange={(e) => setStop(e.target.value)}
          />
        </label>
      </div>
      <fieldset className="day-picker" aria-label="Days">
        {DAYS.map((label, day) => (
          <button
            key={label}
            type="button"
            aria-pressed={days.includes(day)}
            onClick={() =>
              setDays((d) => (d.includes(day) ? d.filter((x) => x !== day) : [...d, day]))
            }
          >
            {label}
          </button>
        ))}
      </fieldset>
      {error && (
        <div className="error-line" role="alert">
          {error}
        </div>
      )}
      <div className="flex items-center gap-2">
        {current && (
          <button
            type="button"
            className="btn"
            data-variant="ghost"
            disabled={save.isPending}
            onClick={() => submit(true)}
          >
            Turn off
          </button>
        )}
        <span className="flex-1" />
        <button type="button" className="btn" data-variant="ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          data-variant="primary"
          disabled={save.isPending}
          onClick={() => submit(false)}
        >
          Save
        </button>
      </div>
    </Dialog>
  );
}

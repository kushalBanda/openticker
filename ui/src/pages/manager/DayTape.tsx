import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { type KeyboardEvent, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { type ManagerDaySummary, useManagerDays } from "../../api/queries";
import { Calendar, type DayMark, monthOf, monthSpan, shiftMonth } from "../../components/Calendar";
import { Popover } from "../../components/Popover";
import { dayTitle } from "../../lib/brain";
import { direction, rupees } from "../../lib/format";
import { tapeHeights, tapeWeeks, tapeWindow } from "../../lib/manager";

/** Calendar days the tape reaches back: about six weeks of trading days. */
const REACH = 40;

type Vars = Record<`--${string}`, string | number>;

const dollars = (usd: number) => `$${usd.toFixed(2)}`;

/** A day in a line: what the desk made, and the looks it took. */
function dayLine(day: ManagerDaySummary): string {
  const net = day.net == null ? "not recorded" : rupees(day.net, { sign: true });
  const used = day.ran ? `${day.looks} looks, ${dollars(day.cost_usd)}` : "manager off";
  return `${dayTitle(day.trading_date)}, ${net}, ${used}`;
}

/**
 * The manager's days as a tape (ADR 43): each trading day's result as a bar
 * from the zero line, a dot where it ran. A click opens one as it closed.
 */
export function DayTape({ selected, today }: { selected: string; today: string }) {
  const navigate = useNavigate();
  const [start, end] = tapeWindow(selected, today, REACH);
  const days = useManagerDays(start, end);
  const pickerButton = useRef<HTMLButtonElement>(null);
  const [picking, setPicking] = useState(false);
  const [hovered, setHovered] = useState<ManagerDaySummary | null>(null);
  const list = days.data?.days ?? [];
  const at = list.findIndex((d) => d.trading_date === selected);
  const weeks = tapeWeeks(list.map((d) => d.trading_date));
  const heights = tapeHeights(list.map((d) => d.net));
  const managed = list.filter((d) => d.ran);
  const total = managed.reduce((sum, d) => sum + (d.net ?? 0), 0);
  const pick = (day: string | undefined) => {
    if (day) navigate(day === today ? "/manager" : `/manager/${day}`);
  };
  const onKey = (event: KeyboardEvent) => {
    const step = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
    if (!step || at < 0) return;
    event.preventDefault();
    pick(list[at + step]?.trading_date);
  };

  return (
    <nav className="mgr-tape" aria-label="Its days">
      <button
        type="button"
        className="mgr-tape-step"
        aria-label="The day before"
        disabled={at <= 0}
        onClick={() => pick(list[at - 1]?.trading_date)}
      >
        <ChevronLeft size={16} aria-hidden />
      </button>
      {days.isError ? (
        <p className="error-line mgr-tape-error">Its days didn't load: {days.error.message}</p>
      ) : (
        <div
          className="mgr-tape-days"
          role="listbox"
          aria-label="Trading days"
          onKeyDown={onKey}
          onMouseLeave={() => setHovered(null)}
        >
          {list.map((day, i) => {
            const chosen = day.trading_date === selected;
            const [weekday = "", date = ""] = dayTitle(day.trading_date).split(" ");
            const tone = direction(day.net);
            return (
              <span key={day.trading_date} className="contents" role="presentation">
                {weeks.has(i) && <span className="mgr-tape-week" aria-hidden />}
                <button
                  type="button"
                  role="option"
                  aria-selected={chosen}
                  tabIndex={chosen ? 0 : -1}
                  className="mgr-tape-day"
                  data-ran={day.ran}
                  aria-label={dayLine(day)}
                  onClick={() => pick(day.trading_date)}
                  onMouseEnter={() => setHovered(day)}
                  onFocus={() => setHovered(day)}
                  onBlur={() => setHovered(null)}
                >
                  <span className="mgr-tape-wd" data-today={day.trading_date === today}>
                    {day.trading_date === today ? "Today" : weekday}
                  </span>
                  <span className="mgr-tape-n">{date}</span>
                  <span className="mgr-tape-bar" aria-hidden>
                    {heights[i] ? (
                      <i data-tone={tone} style={{ "--h": heights[i], "--i": i } as Vars} />
                    ) : null}
                  </span>
                  <span className="mgr-tape-ran" aria-hidden />
                </button>
              </span>
            );
          })}
        </div>
      )}
      <button
        type="button"
        className="mgr-tape-step"
        aria-label="The day after"
        disabled={at < 0 || at >= list.length - 1}
        onClick={() => pick(list[at + 1]?.trading_date)}
      >
        <ChevronRight size={16} aria-hidden />
      </button>
      {/* Any day further back: a trading calendar. */}
      <span className="mgr-tape-pick">
        <button
          ref={pickerButton}
          type="button"
          className="mgr-tape-step"
          aria-label="Pick a day"
          title="Pick a day"
          aria-expanded={picking}
          onClick={() => setPicking((open) => !open)}
        >
          <CalendarDays size={16} aria-hidden />
        </button>
        <Popover
          anchor={pickerButton}
          open={picking}
          onClose={() => setPicking(false)}
          label="Pick a day"
        >
          <DayPicker
            selected={selected}
            today={today}
            onPick={(day) => {
              setPicking(false);
              pick(day);
            }}
          />
        </Popover>
      </span>
      {/* The day under the pointer, else the days it managed together. */}
      <div className="mgr-tape-sum" aria-live="polite">
        {hovered ? (
          <>
            <span className="label">{dayTitle(hovered.trading_date)}</span>
            <b className={direction(hovered.net)}>
              {hovered.net == null ? "Not recorded" : rupees(hovered.net, { sign: true })}
            </b>
            <span>
              {hovered.ran
                ? `${hovered.looks} looks · ${dollars(hovered.cost_usd)}`
                : "The manager was off"}
            </span>
          </>
        ) : (
          <>
            <span className="label">Days it managed</span>
            <b className={direction(total)}>
              {managed.length ? rupees(total, { sign: true }) : "None yet"}
            </b>
            <span>
              {managed.length
                ? `${managed.length} ${managed.length === 1 ? "day" : "days"} · ${dollars(managed.reduce((s, d) => s + d.cost_usd, 0))}`
                : `in the last ${list.length} trading days`}
            </span>
          </>
        )}
      </div>
    </nav>
  );
}

/**
 * Any of its days, a month at a time: each trading day tinted by what the
 * desk made, dotted where the manager ran; quick ways to today, the day
 * before and a month back.
 */
function DayPicker({
  selected,
  today,
  onPick,
}: {
  selected: string;
  today: string;
  onPick: (day: string) => void;
}) {
  const [month, setMonth] = useState(monthOf(selected));
  const [start, end] = monthSpan(month);
  const days = useManagerDays(start, end < today ? end : today);
  const before = useManagerDays(...monthSpan(shiftMonth(monthOf(today), -1)));
  const marks = useMemo(() => {
    if (!days.data) return undefined;
    return new Map<string, DayMark>(
      days.data.days.map((d) => [
        d.trading_date,
        {
          net: d.net,
          dot: d.ran,
          detail: [
            d.net == null ? "not recorded" : rupees(d.net, { sign: true }),
            d.ran ? `${d.looks} looks` : "manager off",
          ].join(" · "),
        },
      ]),
    );
  }, [days.data]);
  // The trading day before today, from this month's days or last month's.
  const previous = [...(days.data?.days ?? []), ...(before.data?.days ?? [])]
    .map((d) => d.trading_date)
    .filter((d) => d < today)
    .sort()
    .at(-1);
  const jump = (day: string | undefined) => day && onPick(day);
  return (
    <Calendar
      month={month}
      onMonth={setMonth}
      value={selected}
      onPick={onPick}
      marks={marks}
      max={today}
      today={today}
      footer={
        <>
          <button type="button" className="chip" onClick={() => jump(today)}>
            Today
          </button>
          <button
            type="button"
            className="chip"
            disabled={!previous}
            onClick={() => jump(previous)}
          >
            Previous day
          </button>
          <button
            type="button"
            className="chip"
            onClick={() => {
              setMonth(shiftMonth(monthOf(today), -1));
            }}
          >
            Last month
          </button>
        </>
      }
    />
  );
}

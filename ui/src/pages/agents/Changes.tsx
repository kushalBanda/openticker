import {
  ArrowLeftRight,
  Brain,
  CircleCheck,
  FileCode,
  Inbox,
  List,
  ShoppingCart,
  Workflow,
} from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import {
  type AgentTurn,
  type ChatChange,
  useCancelOrder,
  useOrders,
  useStrategies,
} from "../../api/queries";
import { describe, pageOf } from "../../lib/events";
import { istMinute } from "../../lib/format";
import type { Order } from "../../lib/orders";
import { useLive } from "../../stream/StreamProvider";

/** A chat turn's changes: the entries recorded between its start and its end. */
export function changesIn(entries: readonly ChatChange[], turn: AgentTurn): ChatChange[] {
  const started = turn.job.started_at;
  if (!started) return [];
  const from = Date.parse(started);
  const to = turn.job.ended_at ? Date.parse(turn.job.ended_at) : Number.POSITIVE_INFINITY;
  return entries.filter((entry) => {
    const at = Date.parse(entry.occurred_at);
    return at >= from && at <= to;
  });
}

function Icon({ entry }: { entry: ChatChange }) {
  const type = entry.event_type;
  if (type.startsWith("Order")) return <ShoppingCart aria-hidden />;
  if (type.startsWith("Strategy")) return <Workflow aria-hidden />;
  if (type.startsWith("Script")) return <FileCode aria-hidden />;
  if (type === "WatchlistChanged") return <List aria-hidden />;
  if (type.startsWith("Position")) return <ArrowLeftRight aria-hidden />;
  if (/Lesson|Proposal|Debrief|Brain/.test(type)) return <Brain aria-hidden />;
  return <Inbox aria-hidden />;
}

/** Each change on one line, linked to its page; an order still open can be cancelled here. */
export function ChangeRows({
  entries,
  showTime = false,
}: {
  entries: readonly ChatChange[];
  showTime?: boolean;
}) {
  const strategies = useStrategies().data?.strategies;
  const names = useMemo(
    () => new Map((strategies ?? []).map((s) => [s.strategy_id, s.name])),
    [strategies],
  );
  const { status } = useLive();
  const broker = status?.broker;
  const placed = entries.some((e) => e.event_type === "OrderPlaced");
  const orders = useOrders(placed ? broker : undefined).data?.orders;
  const cancel = useCancelOrder();
  return (
    <>
      {entries.map((entry) => {
        const said = describe(entry, names);
        const page = pageOf(entry);
        const orderId = entry.details.order_id;
        const open: Order | undefined =
          entry.event_type === "OrderPlaced" && typeof orderId === "string"
            ? orders?.find((o) => o.order_id === orderId && o.status === "PENDING")
            : undefined;
        return (
          <li key={entry.id} className="aw-change">
            <Icon entry={entry} />
            <span className="aw-change-what">{said.text}</span>
            {showTime && (
              <span className="aw-change-time">{istMinute(new Date(entry.occurred_at))}</span>
            )}
            {open && broker ? (
              <button
                type="button"
                className="aw-change-act"
                disabled={cancel.isPending}
                onClick={() => cancel.mutate({ orderId: open.order_id, broker })}
              >
                Cancel
              </button>
            ) : (
              page && (
                <Link className="aw-change-act" to={page}>
                  Open
                </Link>
              )
            )}
          </li>
        );
      })}
    </>
  );
}

/** Under an answer: what the agent changed on the desk in that turn. */
export function ChangedCard({ entries }: { entries: readonly ChatChange[] }) {
  if (entries.length === 0) return null;
  const n = entries.length;
  return (
    <section className="aw-changed" aria-label="What changed">
      <h3>
        <CircleCheck className="aw-changed-icon" aria-hidden />
        {n === 1 ? "1 change" : `${n} changes`} on your desk
        <span className="aw-changed-note">paper only</span>
      </h3>
      <ul>
        <ChangeRows entries={[...entries].reverse()} />
      </ul>
    </section>
  );
}

import { Link } from "react-router";
import { useManager } from "../../api/queries";
import { loaded, StatCard } from "../../components/StatCard";
import { MISSING, rupees } from "../../lib/format";

/** What the desk manager gives this strategy (ADR 41), changed on its page. */
export function ManagerCard({ strategyId }: { strategyId: string }) {
  const manager = useManager();
  const line = manager.data?.lines.find((l) => l.key === `strategy:${strategyId}`);
  return (
    <StatCard
      label={line?.set_by === "you" ? "You give it" : "Manager gives it"}
      testId="manager-gives"
      value={loaded(manager, () =>
        line?.capital != null ? rupees(line.capital, { decimals: 0 }) : MISSING,
      )}
      note={
        manager.data && (
          <>
            {line?.stop != null ? `stop at ${rupees(line.stop, { decimals: 0 })} · ` : ""}
            <Link to="/manager">{line ? "change" : "set"} ›</Link>
          </>
        )
      }
    />
  );
}

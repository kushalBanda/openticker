import { useLocation, useNavigate } from "react-router";
import { PORTFOLIO } from "../shell/nav";
import { Segmented } from "./Segmented";

/** Positions, Orders and Trades: one sidebar item, switched here. */
export function PortfolioTabs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  return (
    <div className="page-tabs">
      <Segmented
        label="Portfolio"
        value={pathname}
        onChange={(path) => navigate(path)}
        segments={PORTFOLIO.map((page) => ({ value: page.path, label: page.label }))}
      />
    </div>
  );
}

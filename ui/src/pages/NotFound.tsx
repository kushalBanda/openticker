import { Link } from "react-router";
import { Page } from "../components/Page";

export function NotFound() {
  return (
    <Page title="Not found">
      <div className="tile">
        <p className="m-0 mb-3 text-ink-muted">There is no page at this address.</p>
        <Link to="/">Dashboard ›</Link>
      </div>
    </Page>
  );
}

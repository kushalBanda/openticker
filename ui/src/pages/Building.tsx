import { Page } from "../components/Page";

/** A page whose screen is still being built: its title, and a plain note. */
export function Building({ title }: { title: string }) {
  return (
    <Page title={title}>
      <div className="tile">
        <p className="m-0 text-ink-muted">This page is being built.</p>
      </div>
    </Page>
  );
}

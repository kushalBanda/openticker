import { Link, useLocation } from "react-router";
import { type NavPage, PAGES, SETTINGS } from "./nav";

/** Whether `pathname` is `page` or below it; Dashboard only at "/". */
function covers(page: NavPage, pathname: string): boolean {
  if (page.path === "/") return pathname === "/";
  return [page.path, ...(page.also ?? [])].some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
}

function Item({ page }: { page: NavPage }) {
  const Icon = page.icon;
  const { pathname } = useLocation();
  return (
    <Link
      to={page.path}
      className="nav-item"
      title={page.label}
      aria-current={covers(page, pathname) ? "page" : undefined}
    >
      <Icon aria-hidden />
      <span>{page.label}</span>
    </Link>
  );
}

export function typing(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

export function Sidebar() {
  return (
    <nav className="sidebar" aria-label="Pages">
      <div className="wordmark">OpenTicker</div>
      {PAGES.map((page) => (
        <Item key={page.path} page={page} />
      ))}
      <div className="flex-1" />
      <Item page={SETTINGS} />
    </nav>
  );
}

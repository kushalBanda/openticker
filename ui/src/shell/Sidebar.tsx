import { useEffect } from "react";
import { NavLink, useNavigate } from "react-router";
import { type NavPage, PAGES, SETTINGS } from "./nav";

function Item({ page }: { page: NavPage }) {
  const Icon = page.icon;
  return (
    <NavLink to={page.path} end={page.path === "/"} className="nav-item" title={page.label}>
      <Icon aria-hidden />
      <span>{page.label}</span>
      <span className="keys" aria-hidden>
        g {page.key}
      </span>
    </NavLink>
  );
}

function typing(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

/** "g" then a page's key goes to that page, as in Gmail and Linear. */
function useGoShortcuts() {
  const navigate = useNavigate();
  useEffect(() => {
    let armed = 0;
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
      if (event.key === "g") {
        armed = event.timeStamp;
        return;
      }
      if (armed && event.timeStamp - armed < 1000) {
        const page = [...PAGES, SETTINGS].find((p) => p.key === event.key);
        if (page) navigate(page.path);
      }
      armed = 0;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);
}

export function Sidebar() {
  useGoShortcuts();
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

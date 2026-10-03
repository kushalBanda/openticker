import { useEffect, useState } from "react";
import { useBrokerSession, useNotifications, useSignOut, useVersion } from "../../api/queries";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import {
  desktopSupported,
  turnDesktopOff,
  turnDesktopOn,
  useDesktopNotifications,
} from "../../lib/desktop";
import { brokerName } from "../../lib/format";
import { type ThemeChoice, useThemeChoice } from "../../lib/theme";
import { useActions } from "../../shell/actions";
import { useLive } from "../../stream/StreamProvider";
import { AccountSection, ChargesSection } from "./AccountSection";
import { BrokerSection, InstrumentsSection } from "./BrokerSection";
import { KeysSection } from "./KeysSection";

const SECTIONS = [
  { id: "broker", label: "Broker" },
  { id: "instruments", label: "Instruments" },
  { id: "keys", label: "API keys" },
  { id: "account", label: "Paper account" },
  { id: "charges", label: "Charges" },
  { id: "notifications", label: "Notifications" },
  { id: "app", label: "App" },
];

/** The section in view, for the list on the left: the last whose top has passed under the bar. */
function useInView(): string {
  const [current, setCurrent] = useState(SECTIONS[0]?.id ?? "");
  useEffect(() => {
    const pick = () => {
      const bottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 2;
      let found = SECTIONS[0]?.id ?? "";
      for (const section of SECTIONS) {
        const top = document.getElementById(section.id)?.getBoundingClientRect().top;
        if (top !== undefined && top <= 140) found = section.id;
      }
      setCurrent(bottom ? (SECTIONS.at(-1)?.id ?? found) : found);
    };
    pick();
    window.addEventListener("scroll", pick, { passive: true });
    return () => window.removeEventListener("scroll", pick);
  }, []);
  return current;
}

function NotificationsSection() {
  const channels = useNotifications().data;
  const desktop = useDesktopNotifications();
  const { notify } = useActions();
  const onOff = (on: boolean | undefined) => (on === undefined ? "—" : on ? "On" : "Off");

  return (
    <section className="tile" id="notifications" aria-labelledby="notifications-title">
      <div className="settings-head">
        <h2 id="notifications-title">Notifications</h2>
      </div>
      <div className="kv settings-kv">
        <span className="muted">Desktop notifications</span>
        <span>
          <Segmented
            label="Desktop notifications"
            value={desktop ? "on" : "off"}
            segments={[
              { value: "off", label: "Off" },
              { value: "on", label: "On" },
            ]}
            onChange={async (value) => {
              if (value === "off") return turnDesktopOff();
              if (!(await turnDesktopOn())) {
                notify(
                  desktopSupported()
                    ? "The browser blocked notifications: allow them for this site in its settings."
                    : "This browser can't show notifications.",
                );
              }
            }}
          />
        </span>
        <span className="muted">Slack</span>
        <span>{onOff(channels?.slack)}</span>
        <span className="muted">Email</span>
        <span>{onOff(channels?.email)}</span>
      </div>
      <p className="note settings-note">
        Desktop notifications are for what needs you (a kill, a stop on a fault, an expired session)
        while this tab is in the background. Slack and email are set in <code>.env</code>.
      </p>
    </section>
  );
}

function AppSection() {
  const [theme, setTheme] = useThemeChoice();
  const version = useVersion().data?.version;
  const signOut = useSignOut(false);
  const signOutAll = useSignOut(true);

  return (
    <section className="tile" id="app" aria-labelledby="app-title">
      <div className="settings-head">
        <h2 id="app-title">App</h2>
      </div>
      <div className="kv settings-kv">
        <span className="muted">Theme</span>
        <span>
          <Segmented<ThemeChoice>
            label="Theme"
            value={theme}
            onChange={setTheme}
            segments={[
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
              { value: "system", label: "System" },
            ]}
          />
        </span>
        <span className="muted">Version</span>
        <span className="tabular">{version ?? "—"}</span>
        <span className="muted">Charts</span>
        <span>
          <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
            TradingView Lightweight Charts™
          </a>
        </span>
      </div>
      <div className="settings-row">
        <button type="button" className="btn" onClick={() => signOut.mutate()}>
          Sign out
        </button>
        <button
          type="button"
          className="btn"
          data-variant="ghost"
          onClick={() => signOutAll.mutate()}
        >
          Sign out everywhere
        </button>
      </div>
    </section>
  );
}

export function Settings() {
  const { status } = useLive();
  const broker = status?.broker ?? "zerodha";
  const connected = useBrokerSession(broker).data?.connected ?? false;
  const current = useInView();

  return (
    <Page title="Settings">
      <div className="settings-grid">
        <nav className="settings-nav" aria-label="Settings sections">
          {SECTIONS.map((section) => (
            <a
              key={section.id}
              href={`#${section.id}`}
              aria-current={current === section.id ? "true" : undefined}
              onClick={(event) => {
                event.preventDefault();
                document.getElementById(section.id)?.scrollIntoView({ block: "start" });
              }}
            >
              {section.id === "broker" ? brokerName(broker) : section.label}
            </a>
          ))}
        </nav>
        <div className="settings-sections">
          <BrokerSection broker={broker} />
          <InstrumentsSection broker={broker} connected={connected} />
          <KeysSection />
          <AccountSection />
          <ChargesSection broker={broker} connected={connected} />
          <NotificationsSection />
          <AppSection />
        </div>
      </div>
    </Page>
  );
}

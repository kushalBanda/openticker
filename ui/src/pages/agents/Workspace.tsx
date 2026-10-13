import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { useAgentThread, useThreadChanges, useUpdateThread } from "../../api/queries";
import { useThreadWatch } from "../../stream/threadWatch";
import { Composer } from "./Composer";
import { NewChat } from "./NewChat";
import { Rail } from "./Rail";
import { SearchPalette } from "./SearchPalette";
import { SidePanel } from "./SidePanel";
import { Thread } from "./Thread";

// Whether the side panel is open: this browser's own choice, kept across visits.
const PANEL_KEY = "openticker.agents.panel";
function readPanel(): boolean {
  try {
    return localStorage.getItem(PANEL_KEY) === "open";
  } catch {
    return false;
  }
}
function savePanel(open: boolean) {
  try {
    localStorage.setItem(PANEL_KEY, open ? "open" : "closed");
  } catch {
    // Not kept: it opens closed next time.
  }
}

/**
 * Agents (ADR 40, DESIGN.md "Agents workspace"): chats with the user's own
 * Claude Code or Codex, filed in folders, beside the background reviews and
 * debriefs. The Codex app's layout: a rail of chats, one thread, a composer.
 */
export function Workspace() {
  const { threadId } = useParams();
  const thread = useAgentThread(threadId ?? null);
  const live = useThreadWatch(threadId ?? null);
  const changes = useThreadChanges(threadId ?? null);
  const [panel, setPanel] = useState(readPanel);
  const togglePanel = () =>
    setPanel((was) => {
      savePanel(!was);
      return !was;
    });

  const navigate = useNavigate();
  const update = useUpdateThread();
  const { mutate } = update;

  useEffect(() => {
    document.title = `${thread.data?.title ?? "Agents"} · OpenTicker`;
  }, [thread.data?.title]);

  // A chat on screen is read: once its answer is in, and again whenever a new one lands.
  const unread = thread.data?.unread ?? false;
  useEffect(() => {
    if (!threadId || !unread) return;
    const seen = () => {
      if (document.visibilityState === "visible") mutate({ threadId, change: { read: true } });
    };
    seen();
    document.addEventListener("visibilitychange", seen);
    return () => document.removeEventListener("visibilitychange", seen);
  }, [threadId, unread, mutate]);

  // ⇧⌘O starts a new chat, as in ChatGPT (⌘N belongs to the browser); ⌘G searches them.
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      if (event.shiftKey && key === "o") {
        event.preventDefault();
        navigate("/agents");
      } else if (!event.shiftKey && !event.altKey && key === "g") {
        event.preventDefault();
        setSearching(true);
      } else if (event.altKey && !event.shiftKey && event.code === "KeyB") {
        event.preventDefault();
        setPanel((was) => {
          savePanel(!was);
          return !was;
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <main className="aw-page">
      <div className="aw" data-panel={(threadId && panel) || undefined}>
        <Rail current={threadId ?? null} onSearch={() => setSearching(true)} />
        <section
          className="aw-pane"
          data-new={threadId ? undefined : true}
          aria-label={threadId ? "Chat" : "New chat"}
        >
          {threadId ? (
            <>
              <Thread
                query={thread}
                live={live}
                changes={changes.data?.entries ?? []}
                panel={panel}
                onPanel={togglePanel}
              />
              {thread.data && <Composer thread={thread.data} />}
            </>
          ) : (
            <NewChat />
          )}
        </section>
        {threadId && panel && thread.data && (
          <SidePanel
            thread={thread.data}
            changes={changes.data?.entries ?? []}
            loading={changes.isPending}
          />
        )}
      </div>
      <SearchPalette open={searching} onClose={() => setSearching(false)} />
    </main>
  );
}

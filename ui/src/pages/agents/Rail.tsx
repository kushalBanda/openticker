import { Archive, Folder, FolderOpen, Pin, PinOff, Plug, Search, SquarePen } from "lucide-react";
import { useState, useSyncExternalStore } from "react";
import { Link, useNavigate } from "react-router";
import {
  type AgentThreadSummary,
  type FolderCount,
  useAgentThreads,
  useFolderThreads,
  useUpdateThread,
} from "../../api/queries";
import {
  FOLDER_ORDER,
  type FolderKind,
  folderName,
  relativeTime,
  whereLabel,
} from "../../lib/threads";
import { useToast } from "../../shell/toasts";
import { useServerNow } from "../../stream/StreamProvider";
import { RowMenu } from "./RowMenu";
import { DeleteChatDialog } from "./Thread";

const RECENTS = 5;

// One clock for every row's "12m": it moves on each minute.
const minute = {
  listeners: new Set<() => void>(),
  timer: 0 as ReturnType<typeof setInterval> | 0,
  value: Math.floor(Date.now() / 60_000),
  subscribe(listener: () => void) {
    minute.listeners.add(listener);
    if (minute.timer === 0) {
      minute.timer = setInterval(() => {
        minute.value = Math.floor(Date.now() / 60_000);
        for (const l of minute.listeners) l();
      }, 15_000);
    }
    return () => {
      minute.listeners.delete(listener);
      if (minute.listeners.size === 0 && minute.timer !== 0) {
        clearInterval(minute.timer);
        minute.timer = 0;
      }
    };
  },
};
function useMinute(): number {
  return useSyncExternalStore(minute.subscribe, () => minute.value);
}

function Item({
  to,
  current,
  children,
  child = false,
}: {
  to: string;
  current?: boolean;
  children: React.ReactNode;
  child?: boolean | "deep";
}) {
  return (
    <Link to={to} className="aw-ri" data-child={child} aria-current={current ? "page" : undefined}>
      {children}
    </Link>
  );
}

function running(t: AgentThreadSummary) {
  return t.last_status === "pending" || t.last_status === "running" || t.last_status === "stopping";
}

/** A chat in the rail: its title, where it lives, and when it last moved or
 * that it's working or failed; bold while unread. Pin, Archive and ⋯ on hover. */
function ThreadItem({
  t,
  current,
  child,
}: {
  t: AgentThreadSummary;
  current: string | null;
  child?: boolean | "deep";
}) {
  const update = useUpdateThread();
  const toast = useToast();
  const navigate = useNavigate();
  const now = useServerNow();
  useMinute();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const working = running(t);
  const PinIcon = t.pinned ? PinOff : Pin;
  const pin = () => update.mutate({ threadId: t.thread_id, change: { pinned: !t.pinned } });
  const archive = () =>
    update.mutate(
      { threadId: t.thread_id, change: { archived: true } },
      {
        onSuccess: () => {
          if (t.thread_id === current) navigate("/agents");
          toast({
            text: `“${t.title}” archived`,
            action: {
              label: "Undo",
              run: () => update.mutate({ threadId: t.thread_id, change: { archived: false } }),
            },
          });
        },
        onError: (error) => toast({ text: `Not archived: ${error.message}`, tone: "down" }),
      },
    );

  if (renaming) {
    return (
      <RenameRow
        t={t}
        child={child}
        onDone={(title) => {
          setRenaming(false);
          if (title && title !== t.title) {
            update.mutate({ threadId: t.thread_id, change: { title } });
          }
        }}
      />
    );
  }
  return (
    <div className="aw-row">
      <Item to={`/agents/${t.thread_id}`} current={t.thread_id === current} child={child}>
        <span className="aw-t" data-unread={t.unread || undefined}>
          {t.title}
        </span>
        {!child && <span className="aw-ctx">{whereLabel(t)}</span>}
        {working ? (
          <span className="aw-live" title="Working" />
        ) : t.failed ? (
          <span className="aw-fail">Failed</span>
        ) : (
          t.active_at && <span className="aw-tm">{relativeTime(t.active_at, now())}</span>
        )}
        {t.unread && <span className="sr-only">, unread</span>}
      </Item>
      <span className="aw-row-acts">
        <button
          type="button"
          className="aw-ico"
          aria-label={`${t.pinned ? "Unpin" : "Pin"} ${t.title}`}
          title={t.pinned ? "Unpin" : "Pin"}
          disabled={update.isPending}
          onClick={pin}
        >
          <PinIcon aria-hidden />
        </button>
        <button
          type="button"
          className="aw-ico"
          aria-label={`Archive ${t.title}`}
          title={working ? "Stop the agent to archive this chat" : "Archive"}
          disabled={update.isPending || working}
          onClick={archive}
        >
          <Archive aria-hidden />
        </button>
        <RowMenu
          thread={t}
          onRename={() => setRenaming(true)}
          onPin={pin}
          onArchive={archive}
          onDelete={() => setDeleting(true)}
        />
      </span>
      <DeleteChatDialog
        thread={t}
        open={deleting}
        onClose={() => setDeleting(false)}
        onDeleted={() => {
          if (t.thread_id === current) navigate("/agents");
        }}
      />
    </div>
  );
}

/** A chat's title as a field: Enter keeps it, Escape or an empty one leaves it as it was. */
function RenameRow({
  t,
  child,
  onDone,
}: {
  t: AgentThreadSummary;
  child?: boolean | "deep";
  onDone: (title: string | null) => void;
}) {
  const [value, setValue] = useState(t.title);
  return (
    <div className="aw-ri aw-rename" data-child={child ?? false}>
      <input
        className="aw-rename-input"
        aria-label="Chat name"
        value={value}
        maxLength={80}
        // biome-ignore lint/a11y/noAutofocus: opened by asking to rename
        autoFocus
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => setValue(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") onDone(value.trim() || null);
          if (event.key === "Escape") onDone(null);
        }}
        onBlur={() => onDone(value.trim() || null)}
      />
    </div>
  );
}

/** A folder's chats, asked for once it opens. A strategy's holds its reviews. */
function FolderChats({
  folder,
  subject,
  current,
  deep,
}: {
  folder: FolderKind;
  subject: string | null;
  current: string | null;
  deep: boolean;
}) {
  const chats = useFolderThreads(folder, subject, true);
  if (chats.isPending) return <div className="aw-more">Loading chats</div>;
  if (chats.isError) {
    return (
      <div className="aw-more" role="alert">
        Chats didn't load: {chats.error.message}
      </div>
    );
  }
  return (
    <>
      {chats.data.threads.map((t) => (
        <ThreadItem key={t.thread_id} t={t} current={current} child={deep ? "deep" : true} />
      ))}
    </>
  );
}

/** A folder row that opens in place to its chats. */
function FolderRow({
  folder,
  subject,
  label,
  count,
  nested,
  current,
}: {
  folder: FolderKind;
  subject: string | null;
  label: string;
  count: number;
  nested?: boolean;
  current: string | null;
}) {
  const [open, setOpen] = useState(false);
  const Icon = open ? FolderOpen : Folder;
  return (
    <>
      <button
        type="button"
        className="aw-ri"
        data-child={nested ?? false}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {!nested && <Icon aria-hidden />}
        <span className="aw-t">{label}</span>
        <span className="aw-n">{count}</span>
      </button>
      {open && (
        <FolderChats folder={folder} subject={subject} current={current} deep={nested ?? false} />
      )}
    </>
  );
}

/** New chat, Recents, Folders, Connected agents: the Codex app's sidebar. */
export function Rail({ current, onSearch }: { current: string | null; onSearch: () => void }) {
  const threads = useAgentThreads();
  const list = threads.data?.threads ?? [];
  const pinned = threads.data?.pinned ?? [];
  const counts = threads.data?.counts ?? [];
  const total = (kind: FolderKind) =>
    counts.find((c) => c.folder === kind && c.subject === null)?.threads ?? 0;
  const subjects = (kind: FolderKind): FolderCount[] =>
    counts
      .filter((c) => c.folder === kind && c.subject !== null)
      .sort((a, b) => (a.subject_name ?? "").localeCompare(b.subject_name ?? ""));

  return (
    <nav className="aw-rail scroll" aria-label="Chats">
      <div className="aw-rail-top">
        <h1>Agents</h1>
        <button
          type="button"
          className="aw-ico"
          aria-label="Search chats"
          title="Search chats  ⌘G"
          onClick={onSearch}
        >
          <Search aria-hidden />
        </button>
      </div>
      <Item to="/agents" current={current === null}>
        <SquarePen aria-hidden />
        <span className="aw-t">New chat</span>
        <kbd className="aw-kbd" aria-label="Shift Command O">
          ⇧⌘O
        </kbd>
      </Item>

      {pinned.length > 0 && (
        <>
          <div className="aw-rh">Pinned</div>
          {pinned.map((t) => (
            <ThreadItem key={t.thread_id} t={t} current={current} />
          ))}
        </>
      )}

      <div className="aw-rh">Recents</div>
      {threads.isPending ? (
        <div className="aw-more">Loading chats</div>
      ) : threads.isError ? (
        <div className="aw-more" role="alert">
          Chats didn't load: {threads.error.message}
        </div>
      ) : list.length === 0 ? (
        <div className="aw-more">{pinned.length > 0 ? "No other chats." : "No chats yet."}</div>
      ) : (
        list.slice(0, RECENTS).map((t) => <ThreadItem key={t.thread_id} t={t} current={current} />)
      )}

      <div className="aw-rh">Folders</div>
      {FOLDER_ORDER.map((kind) => {
        if (kind === "strategy" || kind === "script") {
          const inside = subjects(kind);
          const Icon = inside.length > 0 ? FolderOpen : Folder;
          return (
            <div key={kind} className="contents">
              <div className="aw-ri" data-static="true">
                <Icon aria-hidden />
                <span className="aw-t">{folderName(kind)}</span>
              </div>
              {inside.map((c) => (
                <FolderRow
                  key={c.subject}
                  folder={kind}
                  subject={c.subject ?? null}
                  label={c.subject_name ?? `${c.subject} · deleted`}
                  count={c.threads}
                  nested
                  current={current}
                />
              ))}
            </div>
          );
        }
        const count = total(kind);
        return count > 0 ? (
          <FolderRow
            key={kind}
            folder={kind}
            subject={null}
            label={folderName(kind)}
            count={count}
            current={current}
          />
        ) : (
          <div key={kind} className="aw-ri" data-static="true">
            <Folder aria-hidden />
            <span className="aw-t">{folderName(kind)}</span>
          </div>
        );
      })}

      <div className="flex-1" />
      <Item to="/agents/jobs">
        <Plug aria-hidden />
        <span className="aw-t">Connected agents and jobs</span>
      </Item>
    </nav>
  );
}

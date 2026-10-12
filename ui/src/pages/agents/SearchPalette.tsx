import { Command } from "cmdk";
import { Search } from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { Fragment, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router";
import { type SearchKind, type ThreadHit, useSearchThreads } from "../../api/queries";
import { useDebounced } from "../../lib/debounce";
import { duration, ease, spring } from "../../lib/motion";
import { relativeTime, whereLabel } from "../../lib/threads";
import { useServerNow } from "../../stream/StreamProvider";

type Filter = SearchKind | "all" | "archived";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "chats", label: "Chats" },
  { value: "reviews", label: "Reviews" },
  { value: "debriefs", label: "Debriefs" },
  { value: "archived", label: "Archived" },
];

/**
 * ⌘G: find a chat, review or debrief by its title or by what was said in it
 * (ADR 40), the Codex app's search. The archived ones are found here only.
 */
export function SearchPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  return createPortal(
    <AnimatePresence>{open && <Palette onClose={onClose} />}</AnimatePresence>,
    document.body,
  );
}

function Palette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const now = useServerNow();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const settled = useDebounced(query, 150);
  const kind = filter === "all" || filter === "archived" ? null : filter;
  const search = useSearchThreads(settled, kind, filter === "archived");
  const words = query.trim();
  const hits = words.length >= 2 ? (search.data?.hits ?? []) : [];

  const open = (hit: ThreadHit) => {
    onClose();
    navigate(`/agents/${hit.thread.thread_id}`);
  };

  return (
    <m.div
      className="scrim palette-scrim"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: duration.fast } }}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <m.div
        className="palette aw-search"
        role="dialog"
        aria-modal="true"
        aria-label="Search chats"
        initial={{ opacity: 0, scale: 0.98, y: -6 }}
        animate={{ opacity: 1, scale: 1, y: 0, transition: spring.soft }}
        exit={{ opacity: 0, scale: 0.98, transition: { duration: duration.fast, ease: ease.in } }}
      >
        <Command
          label="Search chats"
          shouldFilter={false}
          loop
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onClose();
            }
          }}
        >
          <div className="palette-input">
            <Search aria-hidden />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder="Search chats, reviews and debriefs"
            />
            <span className="kbd">esc</span>
          </div>
          <fieldset className="aw-search-filters" aria-label="Look in">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                aria-pressed={filter === f.value}
                onClick={() => setFilter(f.value)}
              >
                {f.label}
              </button>
            ))}
          </fieldset>
          <Command.List>
            {words.length < 2 ? (
              <div className="aw-search-note">
                Type two letters or more. Titles, your messages and the agent's answers are
                searched.
              </div>
            ) : search.isError ? (
              <div className="aw-search-note" role="alert">
                Search didn't work: {search.error.message}
              </div>
            ) : search.isPending ? (
              <div className="aw-search-note" aria-busy="true">
                Searching
              </div>
            ) : hits.length === 0 ? (
              <Command.Empty>
                {filter === "archived"
                  ? `No archived chat holds “${words}”.`
                  : `No chat holds “${words}”. Archived chats are under Archived.`}
              </Command.Empty>
            ) : (
              hits.map((hit) => (
                <Command.Item
                  key={hit.thread.thread_id}
                  value={hit.thread.thread_id}
                  onSelect={() => open(hit)}
                  className="aw-hit"
                >
                  <span className="aw-hit-top">
                    <b>{hit.thread.title}</b>
                    <span className="aw-ctx">{whereLabel(hit.thread)}</span>
                    {hit.thread.archived && <span className="aw-hit-tag">Archived</span>}
                    <span className="aw-tm">{relativeTime(hit.at, now())}</span>
                  </span>
                  {hit.matched !== "title" && (
                    <span className="aw-hit-snip">
                      {hit.matched === "message" ? "You: " : ""}
                      <Marked text={hit.snippet} words={settled.trim()} />
                    </span>
                  )}
                </Command.Item>
              ))
            )}
          </Command.List>
          <div className="aw-search-foot">
            <span>↑↓ to move</span>
            <span>↵ to open</span>
          </div>
        </Command>
      </m.div>
    </m.div>
  );
}

/** The snippet with each case-blind match of the words in bold. */
function Marked({ text, words }: { text: string; words: string }) {
  if (!words) return <>{text}</>;
  const lower = text.toLowerCase();
  const needle = words.toLowerCase();
  const parts: { text: string; hit: boolean; at: number }[] = [];
  let from = 0;
  for (let at = lower.indexOf(needle); at >= 0; at = lower.indexOf(needle, from)) {
    if (at > from) parts.push({ text: text.slice(from, at), hit: false, at: from });
    parts.push({ text: text.slice(at, at + needle.length), hit: true, at });
    from = at + needle.length;
  }
  if (from < text.length) parts.push({ text: text.slice(from), hit: false, at: from });
  return (
    <>
      {parts.map((part) =>
        part.hit ? (
          <mark key={part.at}>{part.text}</mark>
        ) : (
          <Fragment key={part.at}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}

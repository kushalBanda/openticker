import { Fragment, type ReactNode } from "react";
import { Link } from "react-router";

/** A wikilink's target: [[kind:key|label]]. */
export interface WikiRef {
  kind: string;
  key: string;
}

/** Where a wikilink goes in the app, and the title it shows when it has no
 * label of its own; null leaves it as text. */
export type LinkTo = (ref: WikiRef) => { href: string; title?: string } | null;

/**
 * The little Markdown an agent writes in a review (ADR 29) or a brain note:
 * paragraphs, `-` / `1.` lists, `#` headings, **bold**, *italic*, `code` and
 * [[kind:key|label]] wikilinks. Built from React elements, never HTML: it is
 * text a program wrote, and nothing in it runs. Anything else shows as the
 * text it is.
 */
export function Markdown({
  text,
  className,
  linkTo,
}: {
  text: string;
  className?: string;
  linkTo?: LinkTo;
}) {
  return <div className={`prose ${className ?? ""}`}>{blocks(text, linkTo)}</div>;
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "h"; text: string };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

export function parseBlocks(text: string): Block[] {
  const out: Block[] = [];
  const last = () => out[out.length - 1];
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    const heading = HEADING.exec(line);
    const open = last();
    if (!line.trim()) {
      out.push({ kind: "p", lines: [] }); // a break: the next line starts afresh
    } else if (heading) {
      out.push({ kind: "h", text: heading[1] ?? "" });
    } else if (bullet || numbered) {
      const kind = bullet ? "ul" : "ol";
      const item = (bullet ?? numbered)?.[1] ?? "";
      if (open?.kind === kind) open.items.push(item);
      else out.push({ kind, items: [item] });
    } else if ((open?.kind === "ul" || open?.kind === "ol") && /^\s{2,}/.test(raw)) {
      // A list item's text wrapped onto an indented line.
      open.items[open.items.length - 1] += ` ${line.trim()}`;
    } else if (open?.kind === "p") {
      open.lines.push(line.trim());
    } else {
      out.push({ kind: "p", lines: [line.trim()] });
    }
  }
  return out.filter((b) => b.kind !== "p" || b.lines.length > 0);
}

// **bold**, __bold__, *italic*, _italic_, `code`, [[kind:key|label]]: the
// first that starts earliest wins.
const INLINE =
  /(\*\*|__)(.+?)\1|(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\3(?![\w*])|`([^`]+)`|\[\[(day|strategy|symbol|lesson|proposal|run|order):([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/;

/** A key as the server stores it: a symbol in capitals, anything trimmed. */
function wikiKey(kind: string, key: string): string {
  return kind === "symbol" ? key.trim().toUpperCase() : key.trim();
}

export function inline(text: string, linkTo?: LinkTo): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest) {
    const match = INLINE.exec(rest);
    if (!match) {
      out.push(rest);
      break;
    }
    if (match.index > 0) out.push(rest.slice(0, match.index));
    const [whole, , bold, , italic, code, kind, ref, label] = match;
    if (bold !== undefined) out.push(<strong key={key++}>{inline(bold, linkTo)}</strong>);
    else if (italic !== undefined) out.push(<em key={key++}>{inline(italic, linkTo)}</em>);
    else if (code !== undefined) out.push(<code key={key++}>{code}</code>);
    else {
      const target = { kind: kind ?? "", key: wikiKey(kind ?? "", ref ?? "") };
      const place = linkTo?.(target) ?? null;
      const shown = label?.trim() || place?.title || target.key;
      out.push(
        place ? (
          <Link key={key++} to={place.href} className="wikilink">
            {shown}
          </Link>
        ) : (
          <span key={key++} className="wikilink" data-unresolved>
            {shown}
          </span>
        ),
      );
    }
    rest = rest.slice(match.index + whole.length);
  }
  return out;
}

function blocks(text: string, linkTo?: LinkTo): ReactNode {
  return parseBlocks(text).map((block, i) => {
    switch (block.kind) {
      case "h":
        // biome-ignore lint/suspicious/noArrayIndexKey: blocks never reorder
        return <h3 key={i}>{inline(block.text, linkTo)}</h3>;
      case "ul":
      case "ol": {
        const List = block.kind;
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: blocks never reorder
          <List key={i}>
            {block.items.map((item, n) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: items never reorder
              <li key={n}>{inline(item, linkTo)}</li>
            ))}
          </List>
        );
      }
      default:
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: blocks never reorder
          <p key={i}>
            {block.lines.map((line, n) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: lines never reorder
              <Fragment key={n}>
                {n > 0 && <br />}
                {inline(line, linkTo)}
              </Fragment>
            ))}
          </p>
        );
    }
  });
}

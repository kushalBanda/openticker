import { Fragment, type ReactNode } from "react";

/**
 * The little Markdown an agent writes in a review (ADR 29): paragraphs,
 * `-` / `1.` lists, `#` headings, **bold**, *italic* and `code`. Built from
 * React elements, never HTML: a review is text a program wrote, and nothing
 * in it runs. Anything else shows as the text it is.
 */
export function Markdown({ text, className }: { text: string; className?: string }) {
  return <div className={`prose ${className ?? ""}`}>{blocks(text)}</div>;
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

// **bold**, __bold__, *italic*, _italic_, `code`: the first that starts earliest wins.
const INLINE = /(\*\*|__)(.+?)\1|(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\3(?![\w*])|`([^`]+)`/;

export function inline(text: string): ReactNode[] {
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
    const [whole, , bold, , italic, code] = match;
    if (bold !== undefined) out.push(<strong key={key++}>{inline(bold)}</strong>);
    else if (italic !== undefined) out.push(<em key={key++}>{inline(italic)}</em>);
    else out.push(<code key={key++}>{code}</code>);
    rest = rest.slice(match.index + whole.length);
  }
  return out;
}

function blocks(text: string): ReactNode {
  return parseBlocks(text).map((block, i) => {
    switch (block.kind) {
      case "h":
        // biome-ignore lint/suspicious/noArrayIndexKey: blocks never reorder
        return <h3 key={i}>{inline(block.text)}</h3>;
      case "ul":
      case "ol": {
        const List = block.kind;
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: blocks never reorder
          <List key={i}>
            {block.items.map((item, n) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: items never reorder
              <li key={n}>{inline(item)}</li>
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
                {inline(line)}
              </Fragment>
            ))}
          </p>
        );
    }
  });
}

import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { Markdown, parseBlocks } from "../../src/components/Markdown";

const REVIEW = `**Not yet: 0 of 10 runs after costs.** I give no verdict.

- **No test was set.** \`notes/demo.md\` did not exist.
- **The profit lock can never trigger.** It starts at ₹2,000
  profit, far above one share.
- **Least sure:** the name *demo*.`;

describe("a review's Markdown", () => {
  test("paragraphs and a list, a wrapped item kept whole", () => {
    expect(parseBlocks(REVIEW).map((b) => b.kind)).toEqual(["p", "ul"]);
    const list = parseBlocks(REVIEW)[1];
    expect(list?.kind === "ul" && list.items[1]).toBe(
      "**The profit lock can never trigger.** It starts at ₹2,000 profit, far above one share.",
    );
  });

  test("bold, italic and code become elements, the markers gone", () => {
    const { container } = render(<Markdown text={REVIEW} />);
    expect(container.textContent).not.toMatch(/\*\*|`/);
    expect(container.querySelector("p strong")?.textContent).toBe(
      "Not yet: 0 of 10 runs after costs.",
    );
    expect(container.querySelectorAll("li")).toHaveLength(3);
    expect(container.querySelector("li code")?.textContent).toBe("notes/demo.md");
    expect(container.querySelector("li em")?.textContent).toBe("demo");
  });

  test("numbered lists and headings", () => {
    const { container } = render(<Markdown text={"## Verdict\n1. Keep\n2. Watch the stop"} />);
    expect(container.querySelector("h3")?.textContent).toBe("Verdict");
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
  });

  test("HTML stays text; a lone asterisk or snake_case stays as written", () => {
    const { container } = render(<Markdown text={"<b>x</b> 2 * 3 = 6, max_loss_limit"} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toBe("<b>x</b> 2 * 3 = 6, max_loss_limit");
  });
});

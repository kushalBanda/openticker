import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { domMax, LazyMotion } from "motion/react";
import { useState } from "react";
import { describe, expect, test } from "vitest";
import { Select } from "../../src/components/Select";
import { daysUntil, percent } from "../../src/lib/format";

const OPTIONS = [
  { value: "2026-10-27", label: "27 Oct 2026", hint: "29 d" },
  { value: "2026-11-03", label: "3 Nov 2026" },
  { value: "2026-11-23", label: "23 Nov 2026" },
];

function Harness({ start = "" }: { start?: string }) {
  const [value, setValue] = useState(start);
  return (
    <LazyMotion features={domMax}>
      <Select
        label="Later expiries"
        placeholder="More…"
        value={value}
        onChange={setValue}
        options={OPTIONS}
      />
      <output>{value}</output>
    </LazyMotion>
  );
}

describe("Select", () => {
  test("shows its placeholder until one is chosen, then the choice", async () => {
    render(<Harness />);
    const box = screen.getByRole("combobox", { name: "Later expiries" });
    expect(box.textContent).toBe("More…");
    await userEvent.click(box);
    await userEvent.click(screen.getByRole("option", { name: /^3 Nov 2026/ }));
    expect(box.textContent).toBe("3 Nov 2026");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
  });

  test("works from the keyboard: arrows, a letter, Enter, Escape", async () => {
    render(<Harness start="2026-10-27" />);
    const box = screen.getByRole("combobox");
    box.focus();
    await userEvent.keyboard("{ArrowDown}");
    const list = screen.getByRole("listbox");
    expect(list).toHaveFocus();
    expect(screen.getByRole("option", { selected: true }).textContent).toContain("27 Oct 2026");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.getByRole("status").textContent).toBe("2026-11-23");
    expect(box).toHaveFocus();

    await userEvent.keyboard("{Enter}3{Enter}");
    expect(screen.getByRole("status").textContent).toBe("2026-11-03");

    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(screen.getByRole("status").textContent).toBe("2026-11-03");
  });
});

describe("figures", () => {
  test("a share of capital to one decimal", () => {
    expect(percent(12_509 / 1_00_00_000)).toBe("0.1");
    expect(percent(0.18)).toBe("18.0");
    expect(percent(0)).toBe("0.0");
  });

  test("days to a date, by the exchange's calendar", () => {
    // 28 Sep 2026, 23:00 IST is still the 28th there.
    expect(daysUntil("2026-10-27", new Date("2026-09-28T17:30:00Z"))).toBe(29);
    expect(daysUntil("2026-09-29", new Date("2026-09-28T19:00:00Z"))).toBe(0);
  });
});

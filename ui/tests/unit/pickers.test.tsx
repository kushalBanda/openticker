import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, test } from "vitest";
import { Calendar, type DayMark, monthSpan, shiftMonth } from "../../src/components/Calendar";
import { TimeField } from "../../src/components/TimeField";

function Field({ start = "", optional = false }: { start?: string; optional?: boolean }) {
  const [value, setValue] = useState(start);
  return (
    <TimeField label="Stop" value={value} onChange={setValue} optional={optional} seed="15:30" />
  );
}

const group = () => screen.getByRole("group", { name: "Stop" });
const hour = () => screen.getByRole("spinbutton", { name: "Hour" });
const minute = () => screen.getByRole("spinbutton", { name: "Minute" });

describe("TimeField", () => {
  test("digits fill the hour, then the minutes", () => {
    render(<Field optional />);
    for (const key of "1000")
      fireEvent.keyDown(document.activeElement === minute() ? minute() : hour(), { key });
    expect(group().dataset.value).toBe("10:00");
  });

  test("a first digit that can't start two is the whole hour", () => {
    render(<Field start="09:15" />);
    fireEvent.keyDown(hour(), { key: "7" });
    expect(group().dataset.value).toBe("07:15");
  });

  test("arrows step and wrap; Shift steps the minutes by five", () => {
    render(<Field start="23:58" />);
    fireEvent.keyDown(hour(), { key: "ArrowUp" });
    expect(group().dataset.value).toBe("00:58");
    fireEvent.keyDown(minute(), { key: "ArrowUp", shiftKey: true });
    expect(group().dataset.value).toBe("00:03");
  });

  test("an empty optional field starts from its seed, and Backspace empties it", () => {
    render(<Field optional />);
    fireEvent.keyDown(hour(), { key: "ArrowUp" });
    expect(group().dataset.value).toBe("16:30");
    fireEvent.keyDown(hour(), { key: "Backspace" });
    expect(group().dataset.value).toBe("");
  });
});

describe("Calendar", () => {
  test("months shift across a year and know their last day", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(monthSpan("2028-02")).toEqual(["2028-02-01", "2028-02-29"]);
  });

  test("only trading days can be picked; weekends aren't drawn", () => {
    const marks = new Map<string, DayMark>([
      ["2026-10-01", { net: 1200 }],
      ["2026-10-05", { net: -300, dot: true }],
    ]);
    let picked = "";
    render(
      <Calendar
        month="2026-10"
        onMonth={() => {}}
        value={null}
        onPick={(day) => {
          picked = day;
        }}
        marks={marks}
        max="2026-10-16"
        today="2026-10-16"
      />,
    );
    expect(screen.queryByRole("button", { name: /^2026-10-03/ })).toBeNull(); // a Saturday
    expect(screen.getByRole("button", { name: /^2026-10-02/ })).toBeDisabled(); // a holiday
    fireEvent.click(screen.getByRole("button", { name: /^2026-10-05/ }));
    expect(picked).toBe("2026-10-05");
    expect(screen.getByRole("button", { name: "The month after" })).toBeDisabled();
  });
});

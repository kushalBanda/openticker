import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { type Column, DataTable } from "../../src/components/DataTable";

interface Row {
  name: string;
  qty: number;
}

const columns: Column<Row>[] = [
  { key: "name", head: "Instrument", align: "left", cell: (r) => r.name, sub: () => "NFO" },
  { key: "qty", head: "Qty.", cell: (r) => r.qty },
];

describe("DataTable", () => {
  test("actions render in a hover pill, not a column", () => {
    render(
      <DataTable
        label="Positions"
        columns={columns}
        rows={[{ name: "RELIANCE", qty: 10 }]}
        rowKey={(r) => r.name}
        actions={() => <button type="button">Close</button>}
      />,
    );
    const heads = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(heads).toEqual(["Instrument", "Qty."]);
    const pill = screen.getByRole("button", { name: "Close" }).parentElement;
    expect(pill).toHaveClass("row-actions");
  });

  test("sub renders under the cell", () => {
    render(
      <DataTable
        label="Positions"
        columns={columns}
        rows={[{ name: "NIFTY OCT FUT", qty: 75 }]}
        rowKey={(r) => r.name}
      />,
    );
    const cell = screen.getByText("NIFTY OCT FUT").closest("td") as HTMLElement;
    expect(within(cell).getByText("NFO")).toHaveClass("sub");
  });

  test("numbers right-aligned and never wrapped by default", () => {
    render(
      <DataTable
        label="Positions"
        columns={columns}
        rows={[{ name: "A", qty: 1 }]}
        rowKey={(r) => r.name}
      />,
    );
    const cell = screen.getByText("1").closest("td") as HTMLElement;
    expect(cell).toHaveAttribute("data-align", "right");
    expect(cell).not.toHaveAttribute("data-wrap", "true");
  });
});

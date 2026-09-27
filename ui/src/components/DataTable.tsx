import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  head: ReactNode;
  align?: "left" | "right";
  cell: (row: T) => ReactNode;
  /** A second line under the cell, in note type (DESIGN.md, two-line cells). */
  sub?: (row: T) => ReactNode;
  /** Prose that may wrap; numbers never do. */
  wrap?: boolean;
}

/**
 * A table inside a flush tile (DESIGN.md Tables). Row actions take no
 * column: they show in a glass pill at the end of the first cell on hover,
 * focus or selection, as Kite puts B / S beside the instrument, so they never
 * cover a number.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  actions,
  selected,
  onSelect,
  dense,
  total,
  label,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  actions?: (row: T) => ReactNode;
  selected?: string;
  onSelect?: (key: string) => void;
  dense?: boolean;
  /** The total row's cells after its label, lined up from the second column. */
  total?: ReactNode;
  label: string;
}) {
  return (
    <table className="table" data-dense={dense ?? false} aria-label={label}>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key} scope="col" data-align={column.align ?? "right"}>
              {column.head}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const key = rowKey(row);
          return (
            <tr
              key={key}
              aria-selected={selected === undefined ? undefined : selected === key}
              onClick={onSelect ? () => onSelect(key) : undefined}
            >
              {columns.map((column, i) => (
                <td
                  key={column.key}
                  data-align={column.align ?? "right"}
                  data-wrap={column.wrap}
                  className={i === 0 && actions ? "has-actions" : undefined}
                >
                  {column.cell(row)}
                  {column.sub && <div className="sub">{column.sub(row)}</div>}
                  {i === 0 && actions && <div className="row-actions">{actions(row)}</div>}
                </td>
              ))}
            </tr>
          );
        })}
        {total}
      </tbody>
    </table>
  );
}

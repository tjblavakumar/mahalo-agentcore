"use client";

import type { TableSpec, VizValue } from "@/types/viz";

interface TableRendererProps {
  spec: TableSpec;
}

function formatCell(value: VizValue): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

/** Renders a plain HTML table from a validated TableSpec (no charting lib). */
export default function TableRenderer({ spec }: TableRendererProps) {
  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-sm border-collapse">
        <thead className="sticky top-0 bg-gray-50">
          <tr>
            {spec.columns.map((c) => (
              <th
                key={c.key}
                className="text-left font-medium text-gray-700 px-3 py-2 border-b border-gray-200"
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.length === 0 ? (
            <tr>
              <td
                colSpan={spec.columns.length}
                className="px-3 py-6 text-center text-gray-400"
              >
                No rows
              </td>
            </tr>
          ) : (
            spec.rows.map((row, ri) => (
              <tr key={ri} className="even:bg-gray-50/50">
                {spec.columns.map((c) => (
                  <td key={c.key} className="px-3 py-2 text-gray-700 border-b border-gray-100">
                    {formatCell(row[c.key] ?? null)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

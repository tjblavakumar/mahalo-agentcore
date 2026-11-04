"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import type { ChartSpec } from "@/types/viz";
import { colorAt, shouldVaryColors } from "@/lib/vizColors";

interface ChartRendererProps {
  spec: ChartSpec;
}

/**
 * Renders a line/area/bar/pie chart from a validated ChartSpec via recharts.
 * Bars default to vertical; `orientation: "horizontal"` lays them out sideways.
 * `"use client"` — recharts touches layout/DOM, so it must render client-side
 * (the mounted gate lives in the parent grid/container per design §2).
 */
export default function ChartRenderer({ spec }: ChartRendererProps) {
  const showLegend = spec.series.length > 1;
  const color = colorAt;
  const vary = shouldVaryColors(spec);

  // Pie: one series, each data row is a slice (name from xKey, value from the
  // series dataKey). Slice colors come from the shared palette (lib/vizColors).
  if (spec.type === "pie") {
    const valueKey = spec.series[0].dataKey;
    return (
      <ResponsiveContainer width="100%" height="100%">
        <PieChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <Tooltip />
          <Legend />
          <Pie
            data={spec.data}
            dataKey={valueKey}
            nameKey={spec.xKey}
            name={spec.series[0].name}
            outerRadius="80%"
            label
          >
            {spec.data.map((_, index) => (
              <Cell key={`cell-${index}`} fill={colorAt(index)} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      {spec.type === "line" ? (
        <LineChart data={spec.data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={spec.xKey} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          {showLegend && <Legend />}
          {spec.series.map((s, i) => (
            <Line
              key={s.dataKey}
              type="monotone"
              dataKey={s.dataKey}
              name={s.name}
              stroke={color(i)}
              dot={false}
            />
          ))}
        </LineChart>
      ) : spec.type === "area" ? (
        <AreaChart data={spec.data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={spec.xKey} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          {showLegend && <Legend />}
          {spec.series.map((s, i) => (
            <Area
              key={s.dataKey}
              type="monotone"
              dataKey={s.dataKey}
              name={s.name}
              stroke={color(i)}
              fill={color(i)}
              fillOpacity={0.2}
            />
          ))}
        </AreaChart>
      ) : spec.orientation === "horizontal" ? (
        // Horizontal bars: recharts lays them out with layout="vertical", the
        // numeric axis on X and the category (xKey) axis on Y.
        <BarChart
          data={spec.data}
          layout="vertical"
          margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis type="number" tick={{ fontSize: 12 }} />
          <YAxis type="category" dataKey={spec.xKey} tick={{ fontSize: 12 }} width={96} />
          <Tooltip />
          {showLegend && !vary && <Legend />}
          {spec.series.map((s, i) => (
            <Bar key={s.dataKey} dataKey={s.dataKey} name={s.name} fill={color(i)}>
              {vary &&
                spec.data.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={colorAt(index)} />
                ))}
            </Bar>
          ))}
        </BarChart>
      ) : (
        <BarChart data={spec.data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={spec.xKey} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          {showLegend && !vary && <Legend />}
          {spec.series.map((s, i) => (
            <Bar key={s.dataKey} dataKey={s.dataKey} name={s.name} fill={color(i)}>
              {vary &&
                spec.data.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={colorAt(index)} />
                ))}
            </Bar>
          ))}
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}

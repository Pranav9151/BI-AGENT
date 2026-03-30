/**
 * Smart BI Agent — Waterfall Chart (Phase 9)
 * Shows incremental positive/negative values with running total
 */
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";

interface WaterfallChartProps {
  data: { name: string; value: number }[];
  height?: number;
  showLegend?: boolean;
}

interface WaterfallBar {
  name: string;
  value: number;
  start: number;
  end: number;
  isTotal?: boolean;
}

export function WaterfallChart({ data, height = 350 }: WaterfallChartProps) {
  if (!data.length) return null;

  // Build waterfall data with running total
  const bars: WaterfallBar[] = [];
  let running = 0;

  data.forEach((d, i) => {
    const start = running;
    running += d.value;
    bars.push({
      name: d.name,
      value: d.value,
      start: Math.min(start, running),
      end: Math.max(start, running),
    });
  });

  // Add total bar
  bars.push({
    name: "Total",
    value: running,
    start: 0,
    end: running,
    isTotal: true,
  });

  const chartData = bars.map((b) => ({
    name: b.name,
    invisible: b.start,
    bar: b.end - b.start,
    value: b.value,
    isTotal: b.isTotal,
    isPositive: b.value >= 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={chartData} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 10, fill: "#94a3b8" }}
          angle={-25}
          textAnchor="end"
          height={50}
          axisLine={{ stroke: "#334155" }}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "#94a3b8" }}
          axisLine={{ stroke: "#334155" }}
          tickFormatter={(v: number) =>
            v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v)
          }
        />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const item = payload[0]?.payload;
            return (
              <div className="bg-slate-800 border border-slate-600/60 rounded-lg px-3 py-2 shadow-xl">
                <p className="text-xs text-slate-400 mb-1">{label}</p>
                <p
                  className="text-sm font-medium"
                  style={{ color: item?.isTotal ? "#8b5cf6" : item?.isPositive ? "#10b981" : "#ef4444" }}
                >
                  {item?.isTotal ? "Total: " : item?.isPositive ? "+" : ""}
                  {item?.value?.toLocaleString()}
                </p>
              </div>
            );
          }}
        />
        <ReferenceLine y={0} stroke="#475569" strokeDasharray="2 2" />
        {/* Invisible base */}
        <Bar dataKey="invisible" stackId="waterfall" fill="transparent" />
        {/* Visible bar */}
        <Bar dataKey="bar" stackId="waterfall" radius={[3, 3, 0, 0]}>
          {chartData.map((entry, i) => (
            <Cell
              key={i}
              fill={entry.isTotal ? "#8b5cf6" : entry.isPositive ? "#10b981" : "#ef4444"}
              fillOpacity={0.75}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

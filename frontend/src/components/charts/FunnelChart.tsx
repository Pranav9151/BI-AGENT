/**
 * Smart BI Agent — Funnel Chart (Phase 9)
 * Custom SVG funnel for conversion/pipeline visualization
 */

const FUNNEL_COLORS = [
  "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
  "#06b6d4", "#ef4444", "#f97316",
];

interface FunnelChartProps {
  data: { name: string; value: number }[];
  height?: number;
}

export function FunnelChart({ data, height = 350 }: FunnelChartProps) {
  if (!data.length) return null;

  const sorted = [...data].sort((a, b) => b.value - a.value);
  const maxVal = sorted[0].value || 1;
  const svgWidth = 500;
  const svgHeight = height;
  const padding = { top: 20, bottom: 20, left: 20, right: 140 };
  const usableH = svgHeight - padding.top - padding.bottom;
  const segH = usableH / sorted.length;
  const maxBarW = svgWidth - padding.left - padding.right;
  const cx = padding.left + maxBarW / 2;

  return (
    <div className="flex items-center justify-center" style={{ height }}>
      <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} width="100%" height="100%">
        {sorted.map((item, i) => {
          const pct = item.value / maxVal;
          const nextPct = i < sorted.length - 1 ? sorted[i + 1].value / maxVal : pct * 0.7;
          const w1 = maxBarW * pct;
          const w2 = maxBarW * nextPct;
          const y = padding.top + i * segH;
          const color = FUNNEL_COLORS[i % FUNNEL_COLORS.length];

          const x1Left = cx - w1 / 2;
          const x1Right = cx + w1 / 2;
          const x2Left = cx - w2 / 2;
          const x2Right = cx + w2 / 2;

          const convRate =
            i > 0 ? ((item.value / sorted[i - 1].value) * 100).toFixed(1) + "%" : "100%";

          return (
            <g key={item.name}>
              {/* Trapezoid segment */}
              <path
                d={`M${x1Left},${y} L${x1Right},${y} L${x2Right},${y + segH - 2} L${x2Left},${y + segH - 2} Z`}
                fill={color}
                fillOpacity={0.7}
                stroke={color}
                strokeWidth={1}
                strokeOpacity={0.3}
                className="transition-opacity hover:fill-opacity-90"
              />
              {/* Label inside */}
              <text
                x={cx}
                y={y + segH / 2 + 1}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="white"
                fontSize={11}
                fontWeight={600}
              >
                {item.value >= 1e6
                  ? `${(item.value / 1e6).toFixed(1)}M`
                  : item.value >= 1e3
                    ? `${(item.value / 1e3).toFixed(1)}K`
                    : item.value.toLocaleString()}
              </text>
              {/* Right label */}
              <text
                x={svgWidth - padding.right + 10}
                y={y + segH / 2 - 5}
                textAnchor="start"
                fill="#e2e8f0"
                fontSize={11}
                fontWeight={500}
              >
                {item.name.length > 16 ? item.name.slice(0, 14) + "…" : item.name}
              </text>
              <text
                x={svgWidth - padding.right + 10}
                y={y + segH / 2 + 10}
                textAnchor="start"
                fill="#64748b"
                fontSize={9}
              >
                {convRate}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

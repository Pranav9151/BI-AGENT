/**
 * Smart BI Agent — Gauge Chart (Phase 9)
 * Custom SVG gauge/speedometer for KPI visualization
 */
import { useMemo } from "react";

interface GaugeChartProps {
  value: number;
  min?: number;
  max?: number;
  label?: string;
  unit?: string;
  thresholds?: { color: string; upTo: number }[];
  height?: number;
}

const DEFAULT_THRESHOLDS = [
  { color: "#ef4444", upTo: 0.33 },
  { color: "#f59e0b", upTo: 0.66 },
  { color: "#10b981", upTo: 1 },
];

export function GaugeChart({
  value,
  min = 0,
  max = 100,
  label,
  unit = "",
  thresholds,
  height = 280,
}: GaugeChartProps) {
  const pct = Math.max(0, Math.min(1, (value - min) / (max - min)));

  const segments = useMemo(() => {
    const t = thresholds || DEFAULT_THRESHOLDS;
    return t.map((seg, i) => {
      const prevUpTo = i > 0 ? t[i - 1].upTo : 0;
      const startAngle = -135 + prevUpTo * 270;
      const endAngle = -135 + seg.upTo * 270;
      return { ...seg, startAngle, endAngle };
    });
  }, [thresholds]);

  const needleAngle = -135 + pct * 270;
  const activeColor =
    (thresholds || DEFAULT_THRESHOLDS).find((t) => pct <= t.upTo)?.color || "#10b981";

  const cx = 150,
    cy = 140,
    r = 100;

  function arcPath(start: number, end: number, radius: number, width: number) {
    const toRad = (d: number) => (d * Math.PI) / 180;
    const outer = radius;
    const inner = radius - width;
    const x1o = cx + outer * Math.cos(toRad(start));
    const y1o = cy + outer * Math.sin(toRad(start));
    const x2o = cx + outer * Math.cos(toRad(end));
    const y2o = cy + outer * Math.sin(toRad(end));
    const x1i = cx + inner * Math.cos(toRad(end));
    const y1i = cy + inner * Math.sin(toRad(end));
    const x2i = cx + inner * Math.cos(toRad(start));
    const y2i = cy + inner * Math.sin(toRad(start));
    const largeArc = end - start > 180 ? 1 : 0;
    return `M${x1o},${y1o} A${outer},${outer} 0 ${largeArc} 1 ${x2o},${y2o} L${x1i},${y1i} A${inner},${inner} 0 ${largeArc} 0 ${x2i},${y2i} Z`;
  }

  const toRad = (d: number) => (d * Math.PI) / 180;
  const needleLen = r - 18;
  const nx = cx + needleLen * Math.cos(toRad(needleAngle));
  const ny = cy + needleLen * Math.sin(toRad(needleAngle));

  const displayVal =
    value >= 1_000_000
      ? `${(value / 1_000_000).toFixed(1)}M`
      : value >= 1_000
        ? `${(value / 1_000).toFixed(1)}K`
        : value.toLocaleString();

  return (
    <div className="flex items-center justify-center" style={{ height }}>
      <svg viewBox="0 0 300 200" width="100%" height="100%" style={{ maxWidth: 360 }}>
        {/* Track segments */}
        {segments.map((seg, i) => (
          <path
            key={i}
            d={arcPath(seg.startAngle, seg.endAngle, r, 14)}
            fill={seg.color}
            opacity={0.15}
          />
        ))}
        {/* Active arc */}
        <path
          d={arcPath(-135, needleAngle, r, 14)}
          fill={activeColor}
          opacity={0.6}
          style={{ transition: "all 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)" }}
        />
        {/* Needle */}
        <line
          x1={cx}
          y1={cy}
          x2={nx}
          y2={ny}
          stroke={activeColor}
          strokeWidth={3}
          strokeLinecap="round"
          style={{ transition: "all 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)" }}
        />
        <circle cx={cx} cy={cy} r={6} fill={activeColor} />
        <circle cx={cx} cy={cy} r={3} fill="#0f172a" />
        {/* Value */}
        <text x={cx} y={cy + 30} textAnchor="middle" fill="white" fontSize={28} fontWeight={700}>
          {displayVal}
          {unit && (
            <tspan fontSize={12} fill="#94a3b8">
              {" "}
              {unit}
            </tspan>
          )}
        </text>
        {label && (
          <text x={cx} y={cy + 50} textAnchor="middle" fill="#64748b" fontSize={11}>
            {label}
          </text>
        )}
        {/* Min/Max labels */}
        <text x={cx - r + 10} y={cy + 25} textAnchor="start" fill="#475569" fontSize={9}>
          {min.toLocaleString()}
        </text>
        <text x={cx + r - 10} y={cy + 25} textAnchor="end" fill="#475569" fontSize={9}>
          {max.toLocaleString()}
        </text>
      </svg>
    </div>
  );
}

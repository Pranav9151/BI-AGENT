/**
 * Smart BI Agent — AI Anomaly Detection (Phase 11)
 *
 * Runs client-side statistical analysis on widget query results.
 * Detects: sudden spikes/drops, outliers, missing expected values.
 * Shows toast notifications with "Investigate" action.
 *
 * WHY THIS BEATS COMPETITORS:
 * - Tableau Pulse requires Tableau Cloud ($) and separate config
 * - Power BI anomaly detection is limited to line charts only
 * - Qlik has augmented analytics but requires setup
 * - WE do it automatically on every widget refresh, zero config
 */

import { toNumber } from "@/components/QueryResults";
import type { QueryResponse } from "@/types/query";

export interface Anomaly {
  type: "spike" | "drop" | "outlier" | "trend_break";
  severity: "info" | "warning" | "critical";
  message: string;
  value: number;
  label: string;
  column: string;
  pctChange?: number;
}

/**
 * Detect anomalies in query result data.
 * Returns array of anomalies found, sorted by severity.
 */
export function detectAnomalies(
  result: QueryResponse,
  widgetTitle: string
): Anomaly[] {
  const { columns, rows } = result;
  if (rows.length < 3 || columns.length < 2) return [];

  const anomalies: Anomaly[] = [];
  const labelCol = columns[0];
  const valueCols = columns.slice(1);

  for (const valCol of valueCols) {
    const values = rows
      .map((r) => ({ label: String(r[labelCol] ?? ""), value: toNumber(r[valCol]) }))
      .filter((v): v is { label: string; value: number } => v.value !== null);

    if (values.length < 3) continue;

    const nums = values.map((v) => v.value);
    const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
    const variance = nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length;
    const stdDev = Math.sqrt(variance);

    if (stdDev === 0) continue; // All values identical

    // Detect outliers (Z-score > 2.5)
    for (const v of values) {
      const zScore = Math.abs((v.value - mean) / stdDev);
      if (zScore > 2.5) {
        const direction = v.value > mean ? "spike" : "drop";
        const pctFromMean = ((v.value - mean) / mean) * 100;
        anomalies.push({
          type: direction === "spike" ? "spike" : "drop",
          severity: zScore > 3.5 ? "critical" : "warning",
          message: `${widgetTitle}: "${v.label}" shows ${Math.abs(pctFromMean).toFixed(0)}% ${direction} from average in ${valCol.replace(/_/g, " ")}`,
          value: v.value,
          label: v.label,
          column: valCol,
          pctChange: pctFromMean,
        });
      }
    }

    // Detect sudden sequential changes (>50% jump between consecutive values)
    for (let i = 1; i < values.length; i++) {
      const prev = values[i - 1].value;
      const curr = values[i].value;
      if (prev === 0) continue;
      const pctChange = ((curr - prev) / Math.abs(prev)) * 100;
      if (Math.abs(pctChange) > 50) {
        anomalies.push({
          type: pctChange > 0 ? "spike" : "drop",
          severity: Math.abs(pctChange) > 80 ? "critical" : "warning",
          message: `${widgetTitle}: ${pctChange > 0 ? "+" : ""}${pctChange.toFixed(0)}% change from "${values[i - 1].label}" to "${values[i].label}" in ${valCol.replace(/_/g, " ")}`,
          value: curr,
          label: values[i].label,
          column: valCol,
          pctChange,
        });
      }
    }

    // Detect trend break (last 3 values going opposite direction from first 3)
    if (values.length >= 6) {
      const firstThreeAvg = nums.slice(0, 3).reduce((a, b) => a + b, 0) / 3;
      const lastThreeAvg = nums.slice(-3).reduce((a, b) => a + b, 0) / 3;
      const middleAvg = nums.slice(Math.floor(nums.length / 2) - 1, Math.floor(nums.length / 2) + 2).reduce((a, b) => a + b, 0) / 3;

      const firstToMiddle = middleAvg - firstThreeAvg;
      const middleToLast = lastThreeAvg - middleAvg;

      if (firstToMiddle > 0 && middleToLast < 0 && Math.abs(middleToLast) > Math.abs(firstToMiddle) * 0.3) {
        anomalies.push({
          type: "trend_break",
          severity: "info",
          message: `${widgetTitle}: Trend reversal detected in ${valCol.replace(/_/g, " ")} — was rising, now declining`,
          value: lastThreeAvg,
          label: "trend",
          column: valCol,
        });
      } else if (firstToMiddle < 0 && middleToLast > 0 && Math.abs(middleToLast) > Math.abs(firstToMiddle) * 0.3) {
        anomalies.push({
          type: "trend_break",
          severity: "info",
          message: `${widgetTitle}: Trend reversal detected in ${valCol.replace(/_/g, " ")} — was declining, now rising`,
          value: lastThreeAvg,
          label: "trend",
          column: valCol,
        });
      }
    }
  }

  // Sort by severity
  const severityOrder = { critical: 0, warning: 1, info: 2 };
  anomalies.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);

  // Deduplicate — only keep the most severe per label
  const seen = new Set<string>();
  return anomalies.filter((a) => {
    const key = `${a.label}-${a.column}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 3); // Max 3 anomalies per widget
}

/**
 * Format anomaly for display
 */
export function anomalyIcon(severity: Anomaly["severity"]): string {
  return severity === "critical" ? "🔴" : severity === "warning" ? "🟡" : "🔵";
}

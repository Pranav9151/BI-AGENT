/**
 * Smart BI Agent - AI Anomaly Detection (Phase 11)
 *
 * Runs client-side statistical analysis on widget query results.
 * Detects: sudden spikes/drops, outliers, missing expected values.
 * Shows toast notifications with "Investigate" action.
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

type LabelAxisKind = "date" | "number" | "categorical";

function detectLabelAxisKind(labels: string[]): LabelAxisKind {
  if (labels.length === 0) return "categorical";

  const numberHits = labels.filter((l) => Number.isFinite(Number(l))).length;
  if (numberHits / labels.length >= 0.9) return "number";

  const dateHits = labels.filter((l) => !Number.isNaN(Date.parse(l))).length;
  if (dateHits / labels.length >= 0.9) return "date";

  return "categorical";
}

/**
 * Detect anomalies in query result data.
 * Returns array of anomalies found, sorted by severity.
 */
export function detectAnomalies(
  result: QueryResponse,
  widgetTitle: string,
  xAxisType?: "numeric" | "text" | "date"
): Anomaly[] {
  const { columns, rows } = result;
  if (rows.length < 3 || columns.length < 2) return [];

  const anomalies: Anomaly[] = [];
  const labelCol = columns[0];
  const valueCols = columns.slice(1);

  for (const valCol of valueCols) {
    const rawValues = rows
      .map((r) => ({ label: String(r[labelCol] ?? ""), value: toNumber(r[valCol]) }))
      .filter((v): v is { label: string; value: number } => v.value !== null);

    if (rawValues.length < 3) continue;

    const inferredLabelAxisKind = detectLabelAxisKind(rawValues.map((v) => v.label));
    const labelAxisKind: LabelAxisKind =
      xAxisType === "date"
        ? "date"
        : xAxisType === "numeric"
          ? "number"
          : xAxisType === "text"
            ? "categorical"
            : inferredLabelAxisKind;
    const values = [...rawValues];
    if (labelAxisKind === "date") {
      values.sort((a, b) => Date.parse(a.label) - Date.parse(b.label));
    } else if (labelAxisKind === "number") {
      values.sort((a, b) => Number(a.label) - Number(b.label));
    }

    const nums = values.map((v) => v.value);
    const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
    const variance = nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length;
    const stdDev = Math.sqrt(variance);

    if (stdDev === 0) continue;

    // Detect outliers (Z-score > 2.5)
    for (const v of values) {
      const zScore = Math.abs((v.value - mean) / stdDev);
      if (zScore > 2.5) {
        const direction = v.value > mean ? "spike" : "drop";
        const pctFromMean = mean === 0 ? undefined : ((v.value - mean) / mean) * 100;
        anomalies.push({
          type: direction,
          severity: zScore > 3.5 ? "critical" : "warning",
          message:
            pctFromMean === undefined
              ? `${widgetTitle}: "${v.label}" shows a ${direction} from average in ${valCol.replace(/_/g, " ")}`
              : `${widgetTitle}: "${v.label}" shows ${Math.abs(pctFromMean).toFixed(0)}% ${direction} from average in ${valCol.replace(/_/g, " ")}`,
          value: v.value,
          label: v.label,
          column: valCol,
          pctChange: pctFromMean,
        });
      }
    }

    // Sequential comparisons only make sense on ordered axes (date/number).
    if (labelAxisKind !== "categorical") {
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
        const middleAvg = nums
          .slice(Math.floor(nums.length / 2) - 1, Math.floor(nums.length / 2) + 2)
          .reduce((a, b) => a + b, 0) / 3;

        const firstToMiddle = middleAvg - firstThreeAvg;
        const middleToLast = lastThreeAvg - middleAvg;

        if (
          firstToMiddle > 0 &&
          middleToLast < 0 &&
          Math.abs(middleToLast) > Math.abs(firstToMiddle) * 0.3
        ) {
          anomalies.push({
            type: "trend_break",
            severity: "info",
            message: `${widgetTitle}: Trend reversal detected in ${valCol.replace(/_/g, " ")} - was rising, now declining`,
            value: lastThreeAvg,
            label: "trend",
            column: valCol,
          });
        } else if (
          firstToMiddle < 0 &&
          middleToLast > 0 &&
          Math.abs(middleToLast) > Math.abs(firstToMiddle) * 0.3
        ) {
          anomalies.push({
            type: "trend_break",
            severity: "info",
            message: `${widgetTitle}: Trend reversal detected in ${valCol.replace(/_/g, " ")} - was declining, now rising`,
            value: lastThreeAvg,
            label: "trend",
            column: valCol,
          });
        }
      }
    }
  }

  // Sort by severity
  const severityOrder = { critical: 0, warning: 1, info: 2 };
  anomalies.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);

  // Deduplicate - only keep the most severe per label
  const seen = new Set<string>();
  return anomalies
    .filter((a) => {
      const key = `${a.label}-${a.column}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 3);
}

/**
 * Format anomaly for display
 */
export function anomalyIcon(severity: Anomaly["severity"]): string {
  return severity === "critical"
    ? "\u{1F534}"
    : severity === "warning"
      ? "\u{1F7E1}"
      : "\u{1F535}";
}

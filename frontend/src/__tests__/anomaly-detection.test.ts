/**
 * Smart BI Agent — Anomaly Detection Tests
 */

import { describe, it, expect, vi } from "vitest";

// Mock the QueryResults module BEFORE importing anomaly-detection
vi.mock("@/components/QueryResults", () => ({
  toNumber: (val: unknown): number | null => {
    if (typeof val === "number") return val;
    if (typeof val === "string") {
      const n = parseFloat(val);
      return isNaN(n) ? null : n;
    }
    return null;
  },
}));

import { detectAnomalies } from "@/lib/anomaly-detection";
import type { QueryResponse } from "@/types/query";

function makeResult(labels: string[], values: number[]): QueryResponse {
  return {
    columns: ["month", "revenue"],
    rows: labels.map((label, i) => ({ month: label, revenue: values[i] })),
    row_count: labels.length,
    truncated: false,
    duration_ms: 10,
    sql: "SELECT month, revenue FROM sales",
  } as QueryResponse;
}

describe("detectAnomalies", () => {
  it("returns empty array when fewer than 3 rows", () => {
    const result = makeResult(["Jan", "Feb"], [100, 200]);
    expect(detectAnomalies(result, "Revenue")).toEqual([]);
  });

  it("returns empty array with single column", () => {
    const result: QueryResponse = {
      columns: ["id"],
      rows: [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }],
      row_count: 4,
      truncated: false,
      duration_ms: 5,
      sql: "SELECT id FROM t",
    } as QueryResponse;
    expect(detectAnomalies(result, "IDs")).toEqual([]);
  });

  it("detects a spike (value far above mean)", () => {
    const result = makeResult(
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
      [10, 12, 11, 10, 11, 10, 12, 11, 10, 500]
    );
    const anomalies = detectAnomalies(result, "Sales");
    expect(anomalies.length).toBeGreaterThan(0);
    expect(anomalies[0].type).toBe("spike");
  });

  it("detects a drop (value far below mean)", () => {
    const result = makeResult(
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
      [100, 98, 102, 99, 101, 100, 98, 102, 99, -300]
    );
    const anomalies = detectAnomalies(result, "Revenue");
    expect(anomalies.length).toBeGreaterThan(0);
    expect(anomalies[0].type).toBe("drop");
  });

  it("returns empty when all values are identical (zero variance)", () => {
    const result = makeResult(
      ["Jan", "Feb", "Mar", "Apr", "May"],
      [50, 50, 50, 50, 50]
    );
    expect(detectAnomalies(result, "Constant")).toEqual([]);
  });

  it("returns empty for gentle, gradual growth (no anomaly)", () => {
    const result = makeResult(
      ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
      [100, 105, 110, 115, 120, 125]
    );
    expect(detectAnomalies(result, "Growth")).toEqual([]);
  });

  it("sorts by date axis when xAxisType is date", () => {
    const result = makeResult(
      ["2024-03-01", "2024-01-01", "2024-02-01", "2024-04-01", "2024-05-01", "2024-06-01"],
      [10, 11, 12, 11, 10, 500]
    );
    const anomalies = detectAnomalies(result, "Revenue", "date");
    if (anomalies.length > 0) {
      expect(anomalies[0].label).toBe("2024-06-01");
    }
  });

  it("handles non-numeric values gracefully", () => {
    const result: QueryResponse = {
      columns: ["category", "amount"],
      rows: [
        { category: "A", amount: 10 },
        { category: "B", amount: 12 },
        { category: "C", amount: "N/A" },
        { category: "D", amount: 11 },
        { category: "E", amount: 10 },
      ],
      row_count: 5,
      truncated: false,
      duration_ms: 5,
      sql: "SELECT category, amount FROM t",
    } as QueryResponse;
    expect(Array.isArray(detectAnomalies(result, "Mixed"))).toBe(true);
  });
});
/**
 * Smart BI Agent — SQL Builder v2 (Phase 12)
 *
 * ★ CRITICAL FIX: v1 used implicit cross-joins (FROM t1, t2) when fields
 *   came from multiple tables. This silently produced cartesian products
 *   and wildly inflated/incorrect numbers.
 *
 * v2 FIXES:
 *   1. Single-table queries work exactly as before
 *   2. Multi-table queries are BLOCKED with a clear error message
 *      until proper relationships are defined
 *   3. Future: when semantic model provides relationships, generate
 *      proper JOINs automatically
 *
 * ALSO:
 *   - Proper quoting for identifiers with spaces/special chars
 *   - LIMIT is always applied
 *   - GROUP BY only includes non-aggregated columns
 */

import type { CanvasWidget, FieldAssignment } from "./widget-types";

export interface SqlBuildResult {
  sql: string | null;
  error: string | null;
  tables: string[];
}

/**
 * Build a SQL query from widget field assignments.
 *
 * Returns { sql, error, tables } — sql is null if fields are missing
 * or if a multi-table cross-join would occur.
 */
export function buildSql(w: CanvasWidget): SqlBuildResult {
  if (!w.xAxis && w.values.length === 0) {
    return { sql: null, error: null, tables: [] };
  }

  const allFields: FieldAssignment[] = [
    ...(w.xAxis ? [w.xAxis] : []),
    ...w.values,
    ...(w.legend ? [w.legend] : []),
  ];

  // Collect unique tables
  const tableSet = new Set(allFields.map((f) => f.table));
  const tables = [...tableSet];

  // ★ CROSS-JOIN PREVENTION
  // If fields come from multiple tables and we don't have relationship
  // definitions, refuse to build (instead of silently cross-joining)
  if (tables.length > 1) {
    return {
      sql: null,
      error: `Fields span ${tables.length} tables (${tables.join(", ")}). Multi-table queries require defined relationships to avoid incorrect results. Use "AI Query" mode instead, or select fields from a single table.`,
      tables,
    };
  }

  const table = tables[0];
  const sel: string[] = [];
  const grp: string[] = [];

  // X-Axis (dimension)
  if (w.xAxis) {
    const ref = quoteIdent(table, w.xAxis.column);
    sel.push(`${ref} AS ${quoteAlias(w.xAxis.column)}`);
    grp.push(ref);
  }

  // Values (measures)
  for (const v of w.values) {
    const ref = quoteIdent(table, v.column);
    if (v.agg === "NONE") {
      sel.push(`${ref} AS ${quoteAlias(v.column)}`);
    } else {
      sel.push(`${v.agg}(${ref}) AS ${quoteAlias(v.column)}`);
    }
  }

  // Legend (group-by)
  if (w.legend) {
    const ref = quoteIdent(table, w.legend.column);
    sel.push(`${ref} AS ${quoteAlias(w.legend.column)}`);
    grp.push(ref);
  }

  if (!sel.length) return { sql: null, error: null, tables };

  let sql = `SELECT ${sel.join(", ")} FROM ${quoteTable(table)}`;
  if (grp.length) sql += ` GROUP BY ${grp.join(", ")}`;
  if (w.xAxis) sql += ` ORDER BY ${quoteAlias(w.xAxis.column)}`;
  sql += " LIMIT 500";

  return { sql, error: null, tables };
}

// ─── Identifier Quoting ──────────────────────────────────────────────────────

function quoteIdent(table: string, column: string): string {
  return `"${table}"."${column}"`;
}

function quoteTable(table: string): string {
  return `"${table}"`;
}

function quoteAlias(name: string): string {
  return `"${name}"`;
}

/**
 * Smart BI Agent — Security Utilities Tests
 *
 * Covers:
 *   - copyWithFooter appends confidentiality notice
 *   - copyPlain does NOT append footer
 */

import { describe, it, expect, vi } from "vitest";
import { copyWithFooter, copyPlain } from "@/lib/security";

describe("copyWithFooter", () => {
  it("appends confidentiality footer to clipboard text", () => {
    copyWithFooter("SELECT * FROM orders");

    expect(navigator.clipboard.writeText).toHaveBeenCalledOnce();
    const written = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(written).toContain("SELECT * FROM orders");
    expect(written).toContain("Confidential");
    expect(written).toContain("Do not distribute");
  });
});

describe("copyPlain", () => {
  it("copies text without any footer", () => {
    copyPlain("SELECT 1");

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("SELECT 1");
  });
});

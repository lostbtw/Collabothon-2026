import { afterEach, describe, expect, it } from "vitest";
import { api, subscribeEvents } from "./client";
import { isRenderableRecommendation } from "./guards";
import { fixtures, resetMockState } from "./mock";

afterEach(resetMockState);
import { http } from "./transport";

describe("mock mode answers every call the pages make", () => {
  it("serves each route's data from the fixtures", async () => {
    expect((await api.companies()).items.map((c) => c.id)).toEqual(["co_borsuk", "co_amalfi"]);
    expect((await api.sources("co_borsuk")).items.length).toBeGreaterThan(0);
    expect((await api.documents("co_borsuk")).items.map((d) => d.id)).toContain("doc_rcpt412");
    expect((await api.document("doc_rcpt412")).matches[0].paid_by).toBe("employee_private");
    expect((await api.accounts("co_borsuk")).total_liquidity_base).toEqual({ amount: "38400.00", currency: "PLN" });
    expect((await api.forecast("co_borsuk")).min_balance.amount.amount).toBe("-7870.00");
    expect((await api.inbox("co_borsuk")).items.map((r) => r.id)).toEqual(["rec_cl01", "rec_412", "rec_fx01", "rec_fx02"]);
    expect((await api.recommendation("rec_cl01")).type).toBe("credit_line");
    expect((await api.activity("co_borsuk")).items.length).toBeGreaterThan(0);
    expect((await api.ledgerSummary("co_borsuk")).kpis.reimbursements_owed.amount).toBe("5169.00");
    expect((await api.chat("Why will I be short?", "co_borsuk")).evidence.length).toBeGreaterThan(0);
  });
  it("filters by company", async () => {
    expect((await api.sources("co_amalfi")).items.map((s) => s.id)).toEqual(["src_bank_pizzeria"]);
    expect((await api.accounts("co_amalfi")).items.map((a) => a.id)).toEqual(["acc_pizzeria"]);
  });
  it("records a decision as a simulated approval", async () => {
    const approval = await api.decide("rec_cl01", { decision: "approved" });
    expect(approval.subject_id).toBe("rec_cl01");
    expect(approval.execution.mode).toBe("simulated");
  });
  it("hands out copies, so pages cannot change the fixtures", async () => {
    const first = await api.recommendation("rec_cl01");
    first.title = "changed";
    expect((await api.recommendation("rec_cl01")).title).not.toBe("changed");
  });
  it("fails loudly on an unknown path or id", async () => {
    await expect(http("GET", "/no-such-path")).rejects.toThrow(/no handler/);
    await expect(api.recommendation("rec_missing")).rejects.toThrow(/rec_missing/);
  });
  it("replays the fixture events", async () => {
    const seen: string[] = [];
    await new Promise<void>((resolve) => {
      const stop = subscribeEvents((e) => {
        seen.push(e.type);
        if (seen.length === fixtures.events.length) {
          stop();
          resolve();
        }
      });
    });
    expect(seen[0]).toBe("raw_item.received");
    expect(seen.at(-1)).toBe("forecast.updated");
  }, 15000);
});

describe("recommendation guard (contracts rule 4)", () => {
  it("accepts every fixture recommendation", () => {
    expect(fixtures.recommendations.every(isRenderableRecommendation)).toBe(true);
  });
  it("rejects a card without evidence, explanation or control level", () => {
    const base = fixtures.recommendations[0];
    expect(isRenderableRecommendation({ ...base, evidence: [] })).toBe(false);
    expect(isRenderableRecommendation({ ...base, explanation: undefined })).toBe(false);
    expect(isRenderableRecommendation({ ...base, control_level: undefined })).toBe(false);
    expect(isRenderableRecommendation(null)).toBe(false);
  });
});

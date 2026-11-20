import { afterEach, describe, expect, it } from "vitest";
import { api } from "../../api/client";
import { fixtures, resetMockState } from "../../api/mock";
import type { Recommendation } from "../../api/types.gen";
import { buildDecision, buildLists, canApprove, describeChanges, editableAmount, impactFacts, listFor, parseAmount, resultHeadline } from "./model";

afterEach(resetMockState);

const creditLine = fixtures.recommendations.find((r) => r.id === "rec_cl01")!;
const advice = fixtures.recommendations.find((r) => r.id === "rec_fx02")!;

describe("parseAmount", () => {
  it("reads the ways an owner types an amount, without floating point", () => {
    expect(parseAmount("25000")).toBe("25000.00");
    expect(parseAmount("25,000.00")).toBe("25000.00");
    expect(parseAmount("25 000")).toBe("25000.00");
    expect(parseAmount("1299,9")).toBe("1299.90");
    expect(parseAmount("0025000.5")).toBe("25000.50");
  });
  it("refuses anything that is not a positive amount", () => {
    for (const bad of ["", "abc", "-5", "0", "0.00", "1.234", "1,2,3", "25000 PLN"]) expect(parseAmount(bad)).toBeNull();
  });
});

describe("decision request", () => {
  it("approves unchanged when the amount was not edited", () => {
    expect(buildDecision(creditLine, "approve", "30000.00")).toEqual({ decision: "approved", channel: "dashboard" });
    expect(buildDecision(creditLine, "approve", null)).toEqual({ decision: "approved", channel: "dashboard" });
  });
  it("sends the edited limit as a change (30,000 -> 25,000)", () => {
    expect(buildDecision(creditLine, "approve", parseAmount("25,000"))).toEqual({
      decision: "approved_with_changes",
      channel: "dashboard",
      changes: { "proposed_action.params.limit": { amount: "25000.00", currency: "PLN" } },
    });
  });
  it("rejects without changes", () => {
    expect(buildDecision(creditLine, "reject", "25000.00")).toEqual({ decision: "rejected", channel: "dashboard" });
  });
  it("only the credit-line limit can be edited; advice and real execution cannot be approved", () => {
    expect(editableAmount(creditLine)?.value).toEqual({ amount: "30000.00", currency: "PLN" });
    expect(editableAmount(advice)).toBeNull();
    expect(canApprove(creditLine)).toBe(true);
    expect(canApprove(advice)).toBe(false);
    expect(canApprove({ ...creditLine, execution_mode: "permitted" })).toBe(false);
  });
});

describe("inbox lists", () => {
  it("shows the fixture cards and the sample ones, and counts them by control level", async () => {
    const lists = buildLists(await api.inbox("co_borsuk"), (await api.recommendations("co_borsuk")).items, []);
    expect(lists.open.map((r) => r.id).slice(0, 4)).toEqual(["rec_cl01", "rec_412", "rec_fx01", "rec_fx02"]);
    expect(lists.counts).toEqual({ all: 9, approval: 5, recommendation: 4, decided: 1 });
    expect(listFor(lists, "recommendation").map((r) => r.id)).toEqual(["rec_fx02", "rec_private01", "rec_missing01", "rec_vatname01"]);
  });
  it("drops a card that has no evidence (contracts rule 4)", async () => {
    const inbox = await api.inbox("co_borsuk");
    inbox.items[0] = { ...inbox.items[0], evidence: [] };
    inbox.items[1] = { ...inbox.items[1], explanation: undefined } as unknown as Recommendation;
    const open = buildLists(inbox, [], []).open.map((r) => r.id);
    expect(open).not.toContain("rec_cl01");
    expect(open).not.toContain("rec_412");
    expect(open).toHaveLength(7);
  });
  it("moves a decided card from open to decided, with its result", async () => {
    const approval = await api.decide("rec_cl01", buildDecision(creditLine, "approve", "25000.00"));
    const lists = buildLists(await api.inbox("co_borsuk"), (await api.recommendations("co_borsuk")).items, (await api.approvals("co_borsuk")).items);
    expect(lists.open.map((r) => r.id)).not.toContain("rec_cl01");
    expect(lists.decided.map((r) => r.id)).toContain("rec_cl01");
    expect(resultHeadline(lists.approvalFor("rec_cl01")!)).toBe("SIMULATED — SIM-CL-2026-0007");
    expect(approval.execution.result).toContain("25,000.00 PLN");
    expect(describeChanges(approval)).toEqual([["Limit", "25,000.00 PLN"]]);
  });
  it("says plainly that a rejection sent nothing", async () => {
    const approval = await api.decide("rec_412", buildDecision(fixtures.recommendations[1], "reject"));
    expect(resultHeadline(approval)).toBe("Rejected. Nothing was sent.");
    expect(approval.execution.reference).toBeNull();
  });
});

describe("impact strip", () => {
  it("takes its figures from the engine's impact block", () => {
    expect(impactFacts(creditLine)).toEqual([
      { label: "Lowest balance now", value: "-7,870 PLN", tone: "danger" },
      { label: "After this action", value: "22,130 PLN", tone: "positive" },
      { label: "Estimated cost", value: "317.00 PLN" },
      { label: "Decide by", value: "27 Nov" },
    ]);
    expect(impactFacts(advice)).toEqual([]);
  });
});

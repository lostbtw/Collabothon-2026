import { afterEach, describe, expect, it } from "vitest";
import { api } from "../../api/client";
import { fixtures, resetMockState } from "../../api/mock";
import { buildTodo, costLabel, doneRecently, topThree } from "./model";

afterEach(resetMockState);

const load = async () => buildTodo((await api.inbox("co_borsuk")).items, await api.forecast("co_borsuk"));

describe("To-do", () => {
  it("lists only owner decisions: three to approve, three to check", async () => {
    const todo = await load();
    expect(todo.needsOk.map((i) => i.id)).toEqual(["rec_412", "gap", "rec_fx01"]);
    expect(todo.check.map((i) => i.id)).toEqual(["rec_private01", "rec_missing01", "rec_vatname01"]);
    expect(todo.count).toBe(6);
    // FX Shield's "no need to hedge" needs no answer, so it is not a to-do.
    expect([...todo.needsOk, ...todo.check].some((i) => i.id === "rec_fx02")).toBe(false);
  });

  it("groups the ways to close the cash gap under it, cheapest first", async () => {
    const gap = (await load()).needsOk.find((i) => i.id === "gap")!;
    expect(gap.title).toBe("Cash runs short from 30 Nov to 7 Dec");
    expect(gap.summary).toContain("For 7 days you would be up to 7,870 PLN short.");
    expect(gap.gap!.options.map((r) => r.id)).toEqual(["rec_chase01", "rec_defer01", "rec_cl01"]);
    expect(gap.gap!.options.map(costLabel)).toEqual(["Free", "Free", "About 317 PLN"]);
  });

  it("approves a simple action in one click and opens the rest first; suggestions link to the payments", async () => {
    const todo = await load();
    expect(todo.needsOk[0].primary).toEqual({ kind: "approve", label: "Pay back (simulated)" });
    expect(todo.needsOk[2].primary.kind).toBe("details");
    expect(todo.check[1].primary).toEqual({ kind: "link", label: "Check", to: "/money/payments?month=2026-10&doc=missing" });
    expect(todo.needsOk[0].summary).toBe("Jan paid for a monitor with his own card and sent the receipt.");
  });

  it("puts two decisions and one suggestion on the Overview", async () => {
    expect(topThree(await load()).map((i) => i.id)).toEqual(["rec_412", "gap", "rec_private01"]);
  });

  it("drops a decided action and shows it under Done recently with its simulated reference", async () => {
    await api.decide("rec_412", { decision: "approved", channel: "dashboard" });
    expect((await load()).needsOk.map((i) => i.id)).not.toContain("rec_412");
    const [activity, approvals, recs] = await Promise.all([api.activity("co_borsuk"), api.approvals("co_borsuk"), api.recommendations("co_borsuk")]);
    const done = doneRecently(activity.items, approvals.items, recs.items, 4);
    expect(done.filter((d) => d.level === "approved").map((d) => d.reference)).toEqual(["SIM-PAY-2026-0412", "SIM-PD-2026-0398"]);
    expect(done).toHaveLength(4);
  });

  it("turns hundreds of match confirmations into one to-do that leads to the payments", async () => {
    const base = fixtures.recommendations.find((r) => r.id === "rec_412")!;
    const matches = Array.from({ length: 407 }, (_, i) => ({ ...base, id: `rec_m${i}`, type: "confirm_match" as const }));
    const todo = buildTodo([...(await api.inbox("co_borsuk")).items, ...matches], await api.forecast("co_borsuk"));
    const bulk = todo.needsOk.find((i) => i.id === "bulk-confirm_match")!;
    expect(bulk).toMatchObject({ title: "407 invoices matched to payments", primary: { kind: "link", to: "/money/payments?doc=to_check" } });
    expect(todo.count).toBe(7);
  });

  it("shows no gap item when the forecast has no gap", async () => {
    const forecast = { ...fixtures.forecasts[0], alerts: [], first_negative_date: null };
    const todo = buildTodo((await api.inbox("co_borsuk")).items, forecast);
    expect(todo.needsOk.map((i) => i.id)).toEqual(["rec_412", "rec_cl01", "rec_fx01", "rec_chase01", "rec_defer01"]);
  });
});

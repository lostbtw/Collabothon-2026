import { afterEach, describe, expect, it } from "vitest";
import { api } from "../../api/client";
import { fixtures, resetMockState } from "../../api/mock";
import { buildTodo, costLabel, doneRecently, headline, sortTodo, topThree } from "./model";

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

  it("every prepared action has its approve button; suggestions link to the payments", async () => {
    const todo = await load();
    expect(todo.needsOk[0].primary).toEqual({ kind: "approve", label: "Pay back" });
    expect(todo.needsOk[2].primary).toEqual({ kind: "approve", label: "Fix the rate" });
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
    const done = doneRecently(activity.items, approvals.items, recs.items, 2);
    expect(done.approved.map((d) => d.reference)).toEqual(["SIM-PAY-2026-0412", "SIM-PD-2026-0398"]);
    expect(done.alone.every((d) => d.level === "analysed_autonomously")).toBe(true);
    expect(done.alone.length).toBeLessThanOrEqual(2);
  });

  it("turns hundreds of match confirmations into one to-do that leads to the payments", async () => {
    const base = fixtures.recommendations.find((r) => r.id === "rec_412")!;
    const matches = Array.from({ length: 407 }, (_, i) => ({ ...base, id: `rec_m${i}`, type: "confirm_match" as const }));
    const todo = buildTodo([...(await api.inbox("co_borsuk")).items, ...matches], await api.forecast("co_borsuk"));
    const bulk = todo.needsOk.find((i) => i.id === "bulk-confirm_match")!;
    expect(bulk).toMatchObject({ title: "407 invoices matched to payments", primary: { kind: "link", to: "/money/payments?doc=to_check" } });
    expect(todo.count).toBe(7);
  });

  it("sorts newest first by default, and by urgency, deadline or amount on request", async () => {
    const todo = await load();
    const all = [...todo.needsOk, ...todo.check];
    const newest = sortTodo(all, "newest").map((i) => i.addedAt);
    expect(newest).toEqual([...newest].sort().reverse());
    const oldest = sortTodo(all, "oldest").map((i) => i.addedAt);
    expect(oldest).toEqual([...oldest].sort());
    expect(sortTodo(all, "urgent")[0].severity).toBe("critical");
    const due = sortTodo(all, "due").map((i) => i.dueBy).filter(Boolean);
    expect(due).toEqual([...due].sort());
    expect(sortTodo(all, "amount").at(-1)!.amount).toBeNull();
  });

  it("turns a log line into a short headline without ids", () => {
    expect(headline("Matched doc_pixel11 to txn_731 automatically (45.00 USD x NBP 4.0170 = 180.77 PLN)")).toBe("Matched an invoice to a payment");
    expect(headline("Read 1,480 items from 5 sources")).toBe("Read 1,480 items from 5 sources");
  });

  it("shows no gap item when the forecast has no gap", async () => {
    const forecast = { ...fixtures.forecasts[0], alerts: [], first_negative_date: null };
    const todo = buildTodo((await api.inbox("co_borsuk")).items, forecast);
    expect(todo.needsOk.map((i) => i.id)).toEqual(["rec_412", "rec_cl01", "rec_fx01", "rec_chase01", "rec_defer01"]);
  });
});

import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { resetMockState } from "../api/mock";
import { cashModel } from "./cashChart";
import { add, compareAmounts, lastFullMonth, monthFigures, monthName, monthRange, percent, previousMonth, recentMonths, subtract, typeOfCategory } from "./costTypes";

afterEach(resetMockState);

describe("money arithmetic on decimal strings", () => {
  it("adds and subtracts in cents, never in floating point", () => {
    expect(add("0.10", "0.20")).toBe("0.30");
    expect(add("-1299.00", "1299.00")).toBe("0.00");
    expect(subtract("131800.00", "124600.00")).toBe("7200.00");
    expect(subtract("100.00", "100.01")).toBe("-0.01");
    expect(compareAmounts("-10.00", "2.00")).toBe(-1);
  });
  it("gives whole percents and 0 for an empty month", () => {
    expect(percent("7800.00", "124600.00")).toBe(6);
    expect(percent("67200.00", "124600.00")).toBe(54);
    expect(percent("1.00", "0.00")).toBe(0);
  });
});

describe("month figures for the Overview", () => {
  it("sums October from the backend's per-category summary", async () => {
    const f = monthFigures(await api.ledgerSummary("co_borsuk", { groupBy: "category", ...monthRange("2026-10") }), "PLN");
    expect(f.income).toEqual({ amount: "131800.00", currency: "PLN" });
    expect(f.costs.amount).toBe("124600.00");
    expect(f.leftOver.amount).toBe("7200.00");
    expect(f.fixed.amount).toBe("83760.00");
    expect(f.unexplained.amount).toBe("7800.00");
    expect(f.types.map((t) => t.type.key)).toEqual(["staff", "taxes", "tools", "travel", "equipment", "office", "services", "unexplained"]);
    expect(f.types[0].amount.amount).toBe("67200.00");
  });
  it("has no data for a month with no rows", async () => {
    expect(monthFigures(await api.ledgerSummary("co_borsuk", monthRange("2026-06")), "PLN").hasData).toBe(false);
    expect(monthFigures(null, "PLN").hasData).toBe(false);
  });
  it("groups any unknown category under 'Not explained yet'", () => {
    expect(typeOfCategory("salaries").label).toBe("Staff");
    expect(typeOfCategory("something_new").key).toBe("unexplained");
  });
});

describe("months", () => {
  it("works out ranges and neighbours, also across a year", () => {
    expect(monthRange("2026-02")).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    expect(previousMonth("2026-01")).toBe("2025-12");
    expect(lastFullMonth("2026-11-21")).toBe("2026-10");
    expect(recentMonths("2026-11-21", 3)).toEqual(["2026-11", "2026-10", "2026-09"]);
    expect(monthName("2026-10")).toBe("October 2026");
  });
});

describe("cash over time", () => {
  it("draws three months of history solid and the forecast dashed, meeting at today", async () => {
    const [history, forecast] = await Promise.all([api.balanceHistory("co_borsuk"), api.forecast("co_borsuk")]);
    const m = cashModel(history, forecast)!;
    expect(m.past).toMatch(/^M52 /);
    expect(m.future).not.toBeNull();
    expect(m.days[0].date).toBe("2026-08-21");
    expect(m.days.find((d) => d.date === "2026-11-20")).toMatchObject({ expected: false, balance: { amount: "38400.00" } });
    expect(m.days.find((d) => d.date === "2026-12-05")).toMatchObject({ expected: true, balance: { amount: "-7870.00" } });
    expect(m.zones).toHaveLength(1);
    expect(m.low?.amount.amount).toBe("-7870.00");
    expect(m.months.map((t) => t.label)).toEqual(["Sep", "Oct", "Nov", "Dec", "Jan"]);
  });
  it("shows only the forecast when there is no history", async () => {
    const m = cashModel(null, await api.forecast("co_borsuk"))!;
    expect(m.past).toBeNull();
    expect(m.days.every((d) => d.expected)).toBe(true);
    expect(cashModel(null, null)).toBeNull();
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { fixtures } from "../api/mock";
import { DashboardView } from "./Dashboard";
import { chartModel, dataNotes, pointAt, weather } from "./dashboard/model";

const forecast = fixtures.forecasts[0];

describe("Home dashboard", () => {
  it("puts the red zone on 30 Nov - 7 Dec and the low on 5 Dec at -7,870", () => {
    const m = chartModel(forecast);
    expect(m.zones).toHaveLength(1);
    expect(m.zones[0]).toMatchObject({ from: "2026-11-30", to: "2026-12-07" });
    expect(m.zones[0].x1).toBeLessThan(m.low.x);
    expect(m.low.x).toBeLessThan(m.zones[0].x2);
    expect(m.low).toMatchObject({ date: "2026-12-05", balance: { amount: "-7870.00", currency: "PLN" } });
    expect(m.zeroY).not.toBeNull();
    expect(m.low.y).toBeGreaterThan(m.zeroY!);
  });

  it("reads the balance that holds on a hovered day", () => {
    const m = chartModel(forecast);
    const dec1 = m.points.find((p) => p.date === "2026-12-01")!;
    expect(pointAt(m, dec1.x + 3)?.balance.amount).toBe("-4629.00");
    expect(pointAt(m, 0)?.date).toBe("2026-11-21");
  });

  it("says storm when the balance goes below zero", () => {
    expect(weather(forecast)).toEqual({ kind: "storm", headline: "Cash gap in 9 days" });
    expect(weather({ ...forecast, first_negative_date: null, min_balance: { date: "2026-12-05", amount: { amount: "50000.00", currency: "PLN" } } }).kind).toBe("sunny");
  });

  it("tells a newcomer what to do: the gap, the low point and a button to the fix", async () => {
    const [accounts, summary, inbox] = await Promise.all([api.accounts("co_borsuk"), api.ledgerSummary("co_borsuk"), api.inbox("co_borsuk")]);
    const html = renderToStaticMarkup(<MemoryRouter><DashboardView accounts={accounts} forecast={forecast} summary={summary} inbox={inbox} /></MemoryRouter>);
    expect(html).toContain("38,400 PLN");
    expect(html).toContain("Cash gap in 9 days");
    expect(html).toContain("Lowest -7,870 PLN on 5 Dec");
    expect(html).toContain('href="/inbox/rec_cl01"');
    expect(html).toContain("Below zero 30 Nov – 7 Dec");
  });

  it("names the source of every forecast component and links to its rows", async () => {
    const [accounts, summary, inbox] = await Promise.all([api.accounts("co_borsuk"), api.ledgerSummary("co_borsuk"), api.inbox("co_borsuk")]);
    const html = renderToStaticMarkup(<MemoryRouter><DashboardView accounts={accounts} forecast={forecast} summary={summary} inbox={inbox} /></MemoryRouter>);
    for (const c of forecast.components) {
      expect(html).toContain(c.label.replace("'", "&#x27;"));
      expect(html).toContain(`Source: ${c.evidence![0].label.replaceAll("'", "&#x27;")}`);
    }
  });
});

describe("second company (organisers' pizzeria data)", () => {
  it("follows the selected company: its account, in EUR, with its as-of date", async () => {
    const amalfi = (await api.companies()).items.find((c) => c.id === "co_amalfi")!;
    expect(amalfi).toMatchObject({ base_currency: "EUR", as_of_date: "2025-05-15" });
    const accounts = await api.accounts("co_amalfi");
    expect(accounts.items.map((a) => a.id)).toEqual(["acc_pizzeria"]);
    await expect(api.forecast("co_amalfi")).rejects.toThrow(/No forecast/);
    const transactions = (await api.transactions("co_amalfi")).items;
    const html = renderToStaticMarkup(<MemoryRouter><DashboardView accounts={accounts} forecast={null} summary={null} inbox={await api.inbox("co_amalfi")} transactions={transactions} /></MemoryRouter>);
    expect(html).toContain("33,266.35 EUR");
    expect(html).not.toContain("PLN");
    expect(html).toContain("No forecast for this company yet.");
  });

  it("notes the converted CHF line and links to it", async () => {
    const notes = dataNotes((await api.transactions("co_amalfi")).items);
    expect(notes).toHaveLength(1);
    expect(notes[0].text).toBe("1 CHF line converted to EUR");
    expect(notes[0].evidence.url).toBe("/transactions/txn_pz0615");
    expect(dataNotes((await api.transactions("co_borsuk")).items)).toEqual([]);
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { fixtures } from "../api/mock";
import { DashboardView } from "./Dashboard";
import { chartModel, dailyBalances, dataNotes, dayAt, pointAt, upcoming, weather } from "./dashboard/model";

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
    for (const c of forecast.components.filter((x) => x.kind !== "opening_balance")) {
      expect(html).toContain(c.label.replace("'", "&#x27;"));
      expect(html).toContain(`Source: ${c.evidence![0].label.replaceAll("'", "&#x27;")}`);
    }
  });
});

describe("Home widgets and chart settings", () => {
  it("lists what is coming by date, with how sure the engine is", () => {
    const list = upcoming(forecast);
    expect(list.map((u) => u.date)).toEqual(["2026-11-25", "2026-11-30", "2026-11-30", "2026-12-07"]);
    expect(list[0]).toMatchObject({ amount: { amount: "-14300.00", currency: "PLN" }, confidence: 0.9 });
    expect(list.at(-1)!.url).toBe("/documents/doc_fv1007");
  });

  it("shows only the chosen range, the payments on the line and the safety buffer", () => {
    const week = chartModel(forecast, { days: 7 });
    expect(week.points.map((p) => p.date)).toEqual(["2026-11-21", "2026-11-25", "2026-11-27"]);
    expect(week.lowVisible).toBe(false);
    expect(week.zones).toEqual([]);
    expect(week.events.map((e) => e.date)).toEqual(["2026-11-25"]);
    const full = chartModel(forecast, { buffer: true });
    expect(full.lowVisible).toBe(true);
    expect(full.events).toHaveLength(4);
    expect(full.bufferY).not.toBeNull();
    expect(full.bufferY!).toBeLessThan(full.zeroY!);
    expect(chartModel(forecast).bufferY).toBeNull();
  });

  it("works day by day: a tick, a hover readout and a balance for every single day", () => {
    const m = chartModel(forecast);
    expect(m.xTicks).toHaveLength(46);
    expect(m.xTicks.slice(0, 3).map((t) => t.day)).toEqual([21, 22, 23]);
    expect(m.xTicks.filter((t) => t.month).map((t) => `${t.day} ${t.month}`)).toEqual(["21 Nov", "1 Dec", "1 Jan"]);
    const days = dailyBalances(forecast);
    expect(days).toHaveLength(46);
    const on = (date: string) => days.find((d) => d.date === date)!.balance.amount;
    expect([on("2026-11-21"), on("2026-11-24"), on("2026-11-29"), on("2026-11-30"), on("2026-12-06"), on("2026-12-07"), on("2027-01-05")])
      .toEqual(["38400.00", "38400.00", "61000.00", "-2169.00", "-7870.00", "73230.00", "52930.00"]);
    const dec3 = m.days.find((d) => d.date === "2026-12-03")!;
    expect(dayAt(m, dec3.x + 4)).toMatchObject({ date: "2026-12-03", balance: { amount: "-4629.00", currency: "PLN" } });
  });

  it("shows costs, upcoming payments, currency risk and accounts as widgets", async () => {
    const [accounts, summary, inbox, fx] = await Promise.all([api.accounts("co_borsuk"), api.ledgerSummary("co_borsuk"), api.inbox("co_borsuk"), api.fxExposure("co_borsuk")]);
    const html = renderToStaticMarkup(<MemoryRouter><DashboardView accounts={accounts} forecast={forecast} summary={summary} inbox={inbox} fx={fx.items} initialView={{ buffer: true }} /></MemoryRouter>);
    for (const text of ["Coming up", "Costs by category", "Currency risk", "Accounts", "Waiting for you", "Safety buffer 10,000 PLN"]) expect(html).toContain(text);
    expect(html).toContain("-58,000 PLN");
    expect(html).toContain("95% sure");
    expect(html).toContain("a bad rate could cost 6,595 PLN of 8,000 PLN profit");
    expect(html).toContain('href="/inbox/rec_fx01"');
    expect(html).toContain("24,730.15 PLN");
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

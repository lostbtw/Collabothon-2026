// The new screens render the sample data the way the Figma design shows it.
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { resetMockState } from "../api/mock";
import { groupChats, whenLabel } from "../components/AskOrdo";
import { monthFigures, monthRange } from "../lib/costTypes";
import { ByClientView, ByPersonView, ByTypeView, MonthlyView, PaymentsView } from "./Money";
import { CashCard, WhereItWent } from "./Overview";
import { TodoView } from "./Todo";
import { buildPayments } from "./money/payments";

afterEach(resetMockState);
const render = (el: ReactNode, url = "/") => renderToStaticMarkup(<MemoryRouter initialEntries={[url]}>{el}</MemoryRouter>);
const october = () => api.ledgerSummary("co_borsuk", { groupBy: "category", ...monthRange("2026-10") });

describe("Overview", () => {
  it("shows cash in the bank, the accounts and what is coming", async () => {
    const html = render(<CashCard accounts={await api.accounts("co_borsuk")} forecast={await api.forecast("co_borsuk")} />);
    expect(html).toContain("38,400 PLN");
    expect(html).toContain("24,730.15 PLN");
    expect(html).toContain("VAT for October");
    expect(html).toContain("-58,000 PLN");
  });
  it("shows where October's money went, each type linking to its payments", async () => {
    const summary = await october();
    const html = render(<WhereItWent f={monthFigures(summary, "PLN")} month="2026-10" summary={summary} />);
    expect(html).toContain("124,600 PLN spent in October");
    expect(html).toContain("Staff");
    expect(html).toContain("67,200 PLN");
    expect(html).toContain("24 payments");
    expect(html).toContain('href="/money/payments?month=2026-10&amp;type=staff"');
  });
});

describe("Money", () => {
  it("by type: costs, fixed share and what is not explained", async () => {
    const html = render(<ByTypeView month="2026-10" summary={await october()} before={await api.ledgerSummary("co_borsuk", monthRange("2026-09"))} currency="PLN" />);
    expect(html).toContain("Costs in October");
    expect(html).toContain("↑ 4,800 PLN vs September");
    expect(html).toContain("67% of all costs");
  });
  it("by person: staff cost, what the team is owed, and why", async () => {
    const html = render(<ByPersonView month="2026-10" data={(await api.peopleCosts("co_borsuk", "2026-10"))!} />);
    expect(html).toContain("67,200 PLN");
    expect(html).toContain("54% of all costs");
    expect(html).toContain("5,169 PLN");
    expect(html).toContain("10 receipts paid with their own cards");
    expect(html).toContain("5,800 salary + 3,400 social security");
    expect(html).toContain("Owner, 2 employees, 4 contractors");
    expect(html).not.toContain("SAMPLE");
  });
  it("by client: who owes what, and what is late", async () => {
    const [clients, inbox] = await Promise.all([api.clients("co_borsuk", "2026-10"), api.inbox("co_borsuk")]);
    const html = render(<ByClientView month="2026-10" data={clients!} fx={inbox.items.filter((r) => r.agent === "fx" && r.control_level === "approval_required")} />);
    expect(html).toContain("291,980 PLN");
    expect(html).toContain("86,020 PLN of it is late");
    expect(html).toContain("62% of October income");
    expect(html).toContain("7 days late");
    expect(html).toContain("Usually pays 23 days late");
    expect(html).toContain("about 162,450 PLN");
    expect(html).toContain("Currency risk");
  });
  it("monthly payments: grouped by type, what is not paid yet, what is paid twice or went up", async () => {
    const html = render(<MonthlyView data={(await api.subscriptions("co_borsuk", "2026-11", "all"))!} month="2026-11" />);
    expect(html).toContain("Staff");
    expect(html).toContain("Tools &amp; hosting");
    expect(html).toContain("Not paid yet in November");
    expect(html).toContain("TaskPilot paid twice");
    expect(html).toContain("Chmura Polska +12%");
    expect(html).toContain("saves 89 PLN a month");
  });
  it("all payments: the list and the panel of the selected payment", async () => {
    const [t, a, c, m, d] = await Promise.all([api.transactions("co_borsuk"), api.accounts("co_borsuk"), api.counterparties("co_borsuk"), api.matches("co_borsuk"), api.documents("co_borsuk")]);
    const all = buildPayments({ transactions: t.items, accounts: a.items, counterparties: c.items, matches: m.items, documents: d.items });
    const html = render(<PaymentsView all={all} month="2026-11" selected="txn_s_sklepik" onChanged={() => {}} />, "/money/payments/txn_s_sklepik");
    expect(html).toContain("Jan, own card");
    expect(html).toContain("Missing");
    expect(html).toContain("No invoice yet");
    expect(html).toContain("Drop a photo or PDF here");
    expect(html).toContain("company card ending 4417");
    expect(html).toMatch(/Showing \d+ of \d+/);
  });
});

describe("To-do", () => {
  it("shows the decisions, the gap with its options and the month close", async () => {
    const [inbox, forecast, recs, approvals, activity] = await Promise.all([api.inbox("co_borsuk"), api.forecast("co_borsuk"), api.recommendations("co_borsuk"), api.approvals("co_borsuk"), api.activity("co_borsuk")]);
    const html = render(<TodoView items={inbox.items} forecast={forecast} recs={recs.items} approvals={approvals.items} activity={activity.items}
      month="2026-10" summary={await october()} people={await api.peopleCosts("co_borsuk", "2026-10")} />, "/todo");
    expect(html).toContain("Needs your OK");
    expect(html).toContain("Cash runs short from 30 Nov to 7 Dec");
    expect(html).toContain("Options, cheapest first");
    expect(html).toContain(">Send reminder</button>");
    expect(html).toContain(">Apply</button>");
    expect(html.replace(/<[^>]+>/g, " ")).not.toMatch(/simulated|SAMPLE/i); // visible text only
    expect(html).toContain("Close October");
    expect(html).toContain("94% done");
    expect(html).toContain("Done · SIM-PD-2026-0398");
    expect(html).not.toContain("No need to hedge");
  });
});

describe("Ask Ordo history", () => {
  it("groups chats by day and week, newest first", async () => {
    const sessions = (await api.chatSessions("co_borsuk"))!.items.map((s) => ({ ...s, lastAt: s.last_at }));
    expect(groupChats(sessions, "2026-11-21").map(([g, items]) => [g, items.length])).toEqual([["Today", 1], ["Yesterday", 2], ["Last week", 3]]);
    expect(whenLabel("2026-11-21T09:44:00Z", "2026-11-21")).toBe("09:44");
    expect(whenLabel("2026-11-13T15:20:00Z", "2026-11-21")).toBe("Fri");
    expect(whenLabel("2026-10-01T15:20:00Z", "2026-11-21")).toBe("1 Oct");
  });
  it("keeps a new chat in the history and answers from the company's numbers", async () => {
    const answer = await api.chat("What does Jan cost us?", "co_borsuk", null);
    expect(answer.answer).toContain("9,200 PLN");
    const sessions = (await api.chatSessions("co_borsuk"))!.items;
    expect(sessions[0]).toMatchObject({ session_id: answer.session_id, title: "What does Jan cost us?", messages: 2 });
    expect((await api.chatSession(answer.session_id, "co_borsuk"))!.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
  });
});

describe("endpoints the backend does not serve yet", () => {
  it("turn into null instead of an error, so the screen can say so", async () => {
    expect(await api.peopleCosts("co_amalfi", "2025-05")).toBeNull();
    expect(await api.settings("co_amalfi")).toBeNull();
    expect(await api.balanceHistory("co_amalfi")).toBeNull();
  });
  it("settings and rules can be changed", async () => {
    const saved = await api.patchSettings("co_borsuk", { alerts: { late_client_days: 10 } });
    expect(saved?.alerts.late_client_days).toBe(10);
    expect((await api.settings("co_borsuk"))!.alerts.safety_buffer).toEqual({ amount: "10000.00", currency: "PLN" });
    await api.deleteRule("rule_koszyk", "co_borsuk");
    expect((await api.rules("co_borsuk"))!.items.map((r) => r.id)).not.toContain("rule_koszyk");
  });
});

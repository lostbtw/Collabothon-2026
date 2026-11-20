import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { LedgerView } from "./Ledger";
import { TransactionsView } from "./Transactions";

describe("Transactions", () => {
  it("shows each company only its own bank lines", async () => {
    expect((await api.transactions("co_borsuk")).items.map((t) => t.id)).toEqual(["txn_731"]);
    expect((await api.transactions("co_amalfi")).items.map((t) => t.id)).toEqual(["txn_pz0615"]);
  });
  it("shows the amount in the account's currency and the original amount beside it", async () => {
    const html = renderToStaticMarkup(<TransactionsView items={(await api.transactions("co_borsuk")).items} parties={[]} />);
    expect(html).toContain("-180.62 PLN");
    expect(html).toContain("-45.00 USD");
    expect(html).toContain("Matched");
  });
  it("marks a converted line and the row an evidence link points at", async () => {
    const html = renderToStaticMarkup(<TransactionsView items={(await api.transactions("co_amalfi")).items} parties={[]} marked="txn_pz0615" />);
    expect(html).toContain('class="marked"');
    expect(html).toContain("converted");
    expect(html).toContain("-4,375.00 EUR");
  });
});

describe("Ledger", () => {
  it("lists the entries with status, payer and lost VAT; the explanation stays closed", async () => {
    const [ledger, summary] = await Promise.all([api.ledger("co_borsuk"), api.ledgerSummary("co_borsuk")]);
    const html = renderToStaticMarkup(<MemoryRouter><LedgerView entries={ledger.items} summary={summary} /></MemoryRouter>);
    expect(html).toContain("5,169 PLN");
    expect(html).toContain("Employee, privately");
    expect(html).toContain("242.90 PLN · lost");
    expect(html).toContain("Proposed");
    expect(html).not.toContain(ledger.items[0].explanation);
  });
});

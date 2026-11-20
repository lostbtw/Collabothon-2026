import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { fixtures, resetMockState } from "../api/mock";
import { DocumentView } from "./Documents";
import { formatMoney } from "../lib/money";
import { buildPatch, fields, flagNotes, whoPaid } from "./documents/model";

afterEach(resetMockState);

const receipt = fixtures.documents.find((d) => d.id === "doc_rcpt412")!;
const typed = (over: Record<string, string> = {}) => ({ ...Object.fromEntries(fields(receipt).map((f) => [f.key, f.input])), ...over }) as Parameters<typeof buildPatch>[1];

describe("Document view", () => {
  it("shows the who-paid banner and the VAT flag for Jan's receipt", async () => {
    const data = await api.document("doc_rcpt412");
    const card = (await api.inbox("co_borsuk")).items.find((r) => r.subject?.id === "doc_rcpt412");
    const html = renderToStaticMarkup(<MemoryRouter><DocumentView data={data} card={card} onSave={async () => {}} /></MemoryRouter>);
    expect(html).toContain("Paid privately by Jan");
    expect(html).toContain("The company owes Jan 1,299.00 PLN.");
    expect(html).toContain("No company tax number: 242.90 PLN VAT cannot be recovered");
    expect(html).toContain('href="/inbox/rec_412"');
    expect(html).toContain("please check");
  });

  it("words the banner and flags from the match, not from the model", () => {
    expect(whoPaid(fixtures.matches[1])).toEqual({ headline: "Paid from a company account", detail: null });
    const t = fixtures.documents[1].totals;
    expect(flagNotes(fixtures.documents[1], fixtures.matches[1])).toEqual([`${formatMoney(t.gross)} = ${formatMoney(t.gross_base)} at ${t.fx!.rate}`, "Bought abroad: you report the VAT yourself (reverse charge)"]);
  });

  it("marks low-confidence and missing fields", () => {
    const byKey = Object.fromEntries(fields(receipt).map((f) => [f.key, f]));
    expect(byKey.buyer_tax_id).toMatchObject({ value: "Not found", low: true, missing: true });
    expect(byKey.gross).toMatchObject({ value: "1,299.00 PLN", low: false });
  });

  it("sends only the changed fields, amounts as decimal strings", () => {
    expect(buildPatch(receipt, typed())).toEqual({ patch: null, error: null });
    expect(buildPatch(receipt, typed({ gross: "1 289,50", buyer_tax_id: "9990000014" }))).toEqual({
      patch: { totals: { ...receipt.totals, gross: { amount: "1289.50", currency: "PLN" } }, buyer: { ...receipt.buyer, tax_id: "9990000014" } },
      error: null,
    });
    expect(buildPatch(receipt, typed({ gross: "abc" })).error).toContain("Total");
    expect(buildPatch(receipt, typed({ issue_date: "20.11.2026" })).error).toContain("Date");
  });

  it("editing a field calls PATCH /documents/{id} and the correction is kept", async () => {
    const { patch } = buildPatch(receipt, typed({ gross: "1289.50" }));
    const updated = await api.patchDocument("doc_rcpt412", patch!);
    expect(updated.totals.gross).toEqual({ amount: "1289.50", currency: "PLN" });
    expect(updated.totals.vat).toEqual(receipt.totals.vat);
    expect((await api.document("doc_rcpt412")).document.totals.gross.amount).toBe("1289.50");
  });
});

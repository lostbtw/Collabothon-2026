import { afterEach, describe, expect, it } from "vitest";
import { api } from "../../api/client";
import { finishMockReads, resetMockState } from "../../api/mock";
import { buildPayments, filterPayments, typeOf, type Payment } from "./payments";

afterEach(resetMockState);

async function payments(): Promise<Payment[]> {
  const [t, a, c, m, d] = await Promise.all([api.transactions("co_borsuk"), api.accounts("co_borsuk"), api.counterparties("co_borsuk"), api.matches("co_borsuk"), api.documents("co_borsuk")]);
  return buildPayments({ transactions: t.items, accounts: a.items, counterparties: c.items, matches: m.items, documents: d.items });
}

describe("all payments", () => {
  it("lists bank lines and receipts paid privately in one list, newest first", async () => {
    const list = await payments();
    const jan = list.find((p) => p.id === "doc_rcpt412")!;
    expect(jan).toMatchObject({ name: "ElektroMarkt Polska S.A.", paidBy: "Jan, own card", doc: "receipt", amount: { amount: "-1299.00", currency: "PLN" }, transaction: null });
    expect(typeOf(jan).label).toBe("Equipment");
    expect(list.find((p) => p.id === "txn_731")).toMatchObject({ paidBy: "Card ·4417 (PLN)", doc: "on_file" });
    expect(list.find((p) => p.id === "txn_s_sklepik")).toMatchObject({ name: "Sklepik.pl", doc: "missing" });
    expect(list.find((p) => p.id === "txn_s_tax1120")).toMatchObject({ paidBy: "PLN account", doc: "not_needed" });
    expect(list.find((p) => p.id === "txn_s_kadr1110")).toMatchObject({ paidBy: "Into PLN account" });
    expect(list.find((p) => p.id === "txn_s_rail")).toMatchObject({ paidBy: "Owner's card ·9021" });
    expect(filterPayments(list, { account: "acc_eur" }).every((p) => p.account?.id === "acc_eur")).toBe(true);
    expect(list.map((p) => p.date)).toEqual([...list.map((p) => p.date)].sort().reverse());
  });

  it("filters by month, type, missing invoice and text", async () => {
    const list = await payments();
    const staff = filterPayments(list, { month: "2026-10", type: "staff" });
    expect(staff.map((p) => p.name)).toEqual(expect.arrayContaining(["Jan Kowalski", "Karolina Mazur", "Social security office"]));
    expect(staff.every((p) => typeOf(p).label === "Staff")).toBe(true);
    expect(filterPayments(list, { month: "2026-11", doc: "missing" }).map((p) => p.id)).toEqual(["txn_s_bistro", "txn_s_sklepik"]);
    expect(filterPayments(list, { q: "sklepik" }).map((p) => p.id)).toEqual(["txn_s_sklepik"]);
    expect(filterPayments(list, { month: "2026-10", type: "income" }).length).toBe(4);
  });

  it("a receipt added for a payment is read, checked, and then counts as on file", async () => {
    const raw = await api.upload(new File(["x"], "faktura.jpg", { type: "image/jpeg" }), { companyId: "co_borsuk", transactionId: "txn_s_sklepik" });
    expect(raw.kind).toBe("upload");
    expect((await payments()).find((p) => p.id === "txn_s_sklepik")!.doc).toBe("missing");
    finishMockReads();
    const read = (await payments()).find((p) => p.id === "txn_s_sklepik")!;
    expect(read.doc).toBe("to_check");
    expect(read.document).toMatchObject({ number: "FV 2026/11/0187", totals: { gross: { amount: "1840.00" }, vat: { amount: "344.07" } }, buyer: { is_company: true } });
    await api.decideMatch(read.match!.id, { decision: "approved", channel: "dashboard" });
    expect((await payments()).find((p) => p.id === "txn_s_sklepik")!.doc).toBe("on_file");
  });
});

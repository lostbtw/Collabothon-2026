import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { EvidenceLink } from "../api/types.gen";
import { Sources, appPath, groupSources } from "./Sources";

const link = (kind: EvidenceLink["kind"], id: string, url: string): EvidenceLink => ({ kind, id, label: id, url });
const many: EvidenceLink[] = [
  link("external", "acc_pln", "https://ordo.example/accounts/acc_pln"),
  link("forecast", "fc_1", "/forecast/fc_1"),
  ...Array.from({ length: 60 }, (_, i) => link("transaction", `txn_${i}`, `/transactions/txn_${i}`)),
  ...Array.from({ length: 50 }, (_, i) => link("document", `doc_${i}`, `/documents/doc_${i}`)),
];

describe("chat answer sources", () => {
  it("shows four chips and puts the rest behind one button", () => {
    const html = renderToStaticMarkup(<MemoryRouter><Sources links={many} /></MemoryRouter>);
    expect(html.match(/class="chip"/g)).toHaveLength(4);
    expect(html).toContain("+108 more sources");
  });
  it("groups the rest by kind, accounts first", () => {
    expect(groupSources(many).map((g) => [g.label, g.links.length])).toEqual([["Accounts", 1], ["Forecast", 1], ["Invoices and receipts", 50], ["Payments", 60]]);
  });
  it("opens links to the backend's own host as app pages", () => {
    expect(appPath("https://ordo.example/transactions/txn_1?x=1")).toBe("/transactions/txn_1?x=1");
    expect(appPath("/documents/doc_1")).toBe("/documents/doc_1");
  });
});

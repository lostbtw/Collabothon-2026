import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { fixtures, resetMockState } from "../api/mock";
import { InboxView } from "./Inbox";
import { buildDecision, buildLists } from "./inbox/model";

afterEach(resetMockState);

const noop = async () => {};
const render = (lists: ReturnType<typeof buildLists>, selectedId?: string) =>
  renderToStaticMarkup(<MemoryRouter><InboxView lists={lists} filter="all" onFilter={() => {}} selectedId={selectedId} onDecide={noop} /></MemoryRouter>);
/** The list cards only: each one is a link, so cut at its closing tag. */
const cards = (html: string) => html.split('class="decision-item').slice(1).map((c) => c.split("</a>")[0]);

describe("Inbox screen", () => {
  it("renders all four fixture cards, each with its control-level badge and SIMULATED where an action would run", async () => {
    const html = render(buildLists(await api.inbox("co_borsuk"), [], []));
    const list = cards(html);
    expect(list).toHaveLength(4);
    for (const r of fixtures.recommendations) expect(html).toContain(r.title);
    for (const card of list.slice(0, 3)) {
      expect(card).toContain("Needs your approval");
      expect(card).toContain("Simulated");
    }
    expect(list[3]).toContain("Recommendation");
    expect(list[3]).not.toContain("Simulated");
  });

  it("does not render a card without evidence", async () => {
    const inbox = await api.inbox("co_borsuk");
    inbox.items[0] = { ...inbox.items[0], evidence: [] };
    const html = render(buildLists(inbox, [], []));
    expect(cards(html)).toHaveLength(3);
    expect(html).not.toContain(fixtures.recommendations[0].title);
  });

  it("shows why, the numbers, the evidence and a SIMULATED approve button for the selected card", async () => {
    const html = render(buildLists(await api.inbox("co_borsuk"), [], []), "rec_cl01");
    expect(html).toContain("Salaries and contractor invoices of 58,000 PLN leave on 30 Nov");
    expect(html).toContain("-28,170 PLN on 21 Dec");
    expect(html).toContain('href="/documents/doc_fv1007"');
    expect(html).toContain("Approve (SIMULATED)");
    expect(html).toContain('value="30,000.00"');
  });

  it("offers no approve button for advice", async () => {
    const html = render(buildLists(await api.inbox("co_borsuk"), [], []), "rec_fx02");
    expect(html).not.toContain("Approve (SIMULATED)");
    expect(html).toContain("Nothing to approve");
  });

  it("after editing 30,000 to 25,000 and approving, shows SIMULATED and the reference", async () => {
    const rec = fixtures.recommendations[0];
    const approval = await api.decide(rec.id, buildDecision(rec, "approve", "25000.00"));
    const html = render(buildLists(await api.inbox("co_borsuk"), [], [], { [rec.id]: { rec, approval } }), rec.id);
    expect(html).toContain("SIMULATED — SIM-CL-2026-0007");
    expect(html).toContain("limit 25,000.00 PLN");
    expect(html).not.toContain("Approve (SIMULATED)");
  });
});

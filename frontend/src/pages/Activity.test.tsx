import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { resetMockState } from "../api/mock";
import { ActivityView, loadDetail } from "./Activity";

afterEach(resetMockState);
const render = (el: React.ReactNode) => renderToStaticMarkup(<MemoryRouter>{el}</MemoryRouter>);

describe("Activity feed", () => {
  it("lists what the agents did, with Undo only where there is something to undo", async () => {
    const { items } = await api.activity("co_borsuk");
    const html = render(<ActivityView items={items} onUndo={async () => {}} />);
    for (const a of items) expect(html).toContain(a.text.replace("'", "&#x27;"));
    expect(html.split(">Undo<").length - 1).toBe(1);
  });

  it("opening a merged purchase shows XML + PDF + photo as one record", async () => {
    const { items } = await api.activity("co_borsuk");
    const merged = items.find((a) => a.subject?.id === "doc_pixel11")!;
    const detail = await loadDetail(merged);
    const html = render(<ActivityView items={[merged]} onUndo={async () => {}} open={{ [merged.at]: detail }} />);
    expect(html).toContain("3 copies → one record");
    for (const label of ["E-invoice (XML)", "PDF by e-mail", "Photo"]) expect(html).toContain(label);
  });

  it("opening the cross-currency match shows how it was matched", async () => {
    const { items } = await api.activity("co_borsuk");
    const matched = items.find((a) => a.subject?.type === "match")!;
    const html = render(<ActivityView items={[matched]} onUndo={async () => {}} open={{ [matched.at]: await loadDetail(matched) }} />);
    expect(html).toContain("45.00 USD x NBP 3.9099 = 175.95 PLN");
  });

  it("undo rejects the automatic match and the line leaves the feed", async () => {
    const before = (await api.activity("co_borsuk")).items;
    const approval = await api.decideMatch("mat_pixel11", { decision: "rejected", channel: "dashboard" });
    expect(approval).toMatchObject({ subject_type: "match", subject_id: "mat_pixel11", decision: "rejected" });
    const after = (await api.activity("co_borsuk")).items;
    expect(after).toHaveLength(before.length - 1);
    expect(after.some((a) => a.subject?.id === "mat_pixel11")).toBe(false);
    expect((await api.matches()).items.find((m) => m.id === "mat_pixel11")!.status).toBe("rejected");
  });
});

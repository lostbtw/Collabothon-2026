import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { fixtures, resetMockState } from "../api/mock";
import { ActivityView, loadDetail } from "./Activity";
import { OrdoDetails } from "./todo/done";
import { byDay, ordoLog, ownerLog, undoKind } from "./todo/model";

afterEach(resetMockState);
const render = (el: React.ReactNode) => renderToStaticMarkup(<MemoryRouter>{el}</MemoryRouter>);
const log = async () => {
  const [activity, approvals, recs] = await Promise.all([api.activity("co_borsuk"), api.approvals("co_borsuk"), api.recommendations("co_borsuk")]);
  return [...ownerLog(approvals.items, recs.items), ...ordoLog(activity.items)];
};

describe("Activity log", () => {
  it("shows what the owner decided and what Ordo did, grouped by day, newest first", async () => {
    const lines = await log();
    const html = render(<ActivityView lines={lines} today="2026-11-21" />);
    expect(html).toContain("Today · 21 Nov 2026");
    expect(html).toContain("Approved by you");
    expect(html).toContain("Done by Ordo");
    expect(html).toContain("Read Jan&#x27;s receipt and worked out that he paid privately");
    const days = byDay(lines).map(([day]) => day);
    expect(days).toEqual([...days].sort().reverse());
  });

  it("offers Undo only for matches Ordo made on its own, never for what the owner decided", async () => {
    const lines = await log();
    expect(lines.filter((d) => d.level === "approved").every((d) => undoKind(d) === null)).toBe(true);
    expect(lines.filter((d) => undoKind(d) === "match")).toHaveLength(1);
    expect(undoKind(lines.find((d) => d.text.startsWith("Read 1,480"))!)).toBeNull();
  });

  it("opening a merged purchase shows XML + PDF + photo as one record", async () => {
    const merged = ordoLog((await api.activity("co_borsuk")).items).find((d) => d.activity?.subject?.id === "doc_pixel11")!;
    const html = render(<OrdoDetails done={merged} detail={await loadDetail(merged.activity!)} />);
    expect(html).toContain("3 copies → one record");
    for (const label of ["E-invoice (XML)", "PDF by e-mail", "Photo"]) expect(html).toContain(label);
  });

  it("opening the cross-currency match shows how it was matched", async () => {
    const matched = ordoLog((await api.activity("co_borsuk")).items).find((d) => d.activity?.subject?.type === "match")!;
    const html = render(<OrdoDetails done={matched} detail={await loadDetail(matched.activity!)} />);
    expect(html).toContain(fixtures.matches.find((m) => m.id === "mat_pixel11")!.reasons[0].detail.split(";")[0]);
  });

  it("undo of a match rejects it and the line leaves the log", async () => {
    const before = (await api.activity("co_borsuk")).items;
    const approval = await api.decideMatch("mat_pixel11", { decision: "rejected", channel: "dashboard" });
    expect(approval).toMatchObject({ subject_type: "match", subject_id: "mat_pixel11", decision: "rejected" });
    const after = (await api.activity("co_borsuk")).items;
    expect(after).toHaveLength(before.length - 1);
    expect((await api.matches()).items.find((m) => m.id === "mat_pixel11")!.status).toBe("rejected");
  });
});

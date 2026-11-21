import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { fixtures } from "../api/mock";
import { isNew } from "../lib/live";
import { CashChart } from "./CashChart";
import { ToastList, toastFor } from "./Toasts";

const event = (type: string) => fixtures.events.find((e) => e.type === type)!;

describe("live updates from the event replay", () => {
  it("says 'New receipt from Jan' when his receipt has been read", async () => {
    const e = event("document.extracted");
    const sender = (await api.document(e.payload.document_id as string)).document.submitted_by?.name;
    expect(toastFor(e, sender)).toEqual({ id: e.id, text: "New receipt from Jan · 1,299.00 PLN", to: "/documents/doc_rcpt412" });
  });

  it("points at the new to-do and at the forecast change (-6,571 -> -7,870)", () => {
    expect(toastFor(event("recommendation.created"))).toMatchObject({ text: "New to-do", to: "/todo#rec_412" });
    expect(toastFor(event("recommendation.created"), null, "Pay Jan back 1,299.00 PLN")?.text).toBe("New to-do: Pay Jan back 1,299.00 PLN");
    expect(toastFor({ ...event("recommendation.created"), payload: { recommendation_id: "rec_m1", type: "confirm_match" } })).toBeNull();
    expect(toastFor(event("forecast.updated"))?.text).toBe("Forecast updated: lowest point -7,870 PLN (was -6,571 PLN)");
    expect(toastFor(event("raw_item.received"))).toBeNull();
  });

  it("renders toasts as links", () => {
    const html = renderToStaticMarkup(<MemoryRouter><ToastList toasts={[toastFor(event("recommendation.created"))!]} onClose={() => {}} /></MemoryRouter>);
    expect(html).toContain('href="/todo#rec_412"');
  });

  it("pulses the lowest point on the cash chart after a forecast update", async () => {
    const forecast = await api.forecast("co_borsuk");
    const html = renderToStaticMarkup(<MemoryRouter><CashChart history={null} forecast={forecast} flash /></MemoryRouter>);
    expect(html).toContain("-7,870 PLN · 5 Dec");
    expect(html).toContain("chart-low flash");
  });

  it("passes each event on once, so a replayed stream does not repeat toasts", () => {
    const known = new Set<string>();
    expect(fixtures.events.map((e) => isNew(e, known))).toEqual([true, true, true, true, true]);
    expect(fixtures.events.some((e) => isNew(e, known))).toBe(false);
  });
});

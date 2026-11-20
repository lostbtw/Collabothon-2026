import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { fixtures } from "../api/mock";
import { isNew } from "../lib/live";
import { DashboardView } from "../pages/Dashboard";
import { ToastList, toastFor } from "./Toasts";

const event = (type: string) => fixtures.events.find((e) => e.type === type)!;

describe("live updates from the event replay", () => {
  it("says 'New receipt from Jan' when his receipt has been read", async () => {
    const e = event("document.extracted");
    const sender = (await api.document(e.payload.document_id as string)).document.submitted_by?.name;
    expect(toastFor(e, sender)).toEqual({ id: e.id, text: "New receipt from Jan · 1,299.00 PLN", to: "/documents/doc_rcpt412" });
  });

  it("points at the new inbox card and at the forecast change (-6,571 -> -7,870)", () => {
    expect(toastFor(event("recommendation.created"))).toMatchObject({ text: "New card in your inbox", to: "/inbox/rec_412" });
    expect(toastFor(event("forecast.updated"))?.text).toBe("Forecast updated: lowest point -7,870 PLN (was -6,571 PLN)");
    expect(toastFor(event("raw_item.received"))).toBeNull();
  });

  it("renders toasts as links", () => {
    const html = renderToStaticMarkup(<MemoryRouter><ToastList toasts={[toastFor(event("recommendation.created"))!]} onClose={() => {}} /></MemoryRouter>);
    expect(html).toContain('href="/inbox/rec_412"');
  });

  it("pulses the low point on the chart and shows the previous value after a forecast update", async () => {
    const [accounts, forecast] = await Promise.all([api.accounts("co_borsuk"), api.forecast("co_borsuk")]);
    const previous = event("forecast.updated").payload.min_balance_previous as { amount: string; currency: string };
    const html = renderToStaticMarkup(<MemoryRouter><DashboardView accounts={accounts} forecast={forecast} summary={null} inbox={null} previousLow={previous} /></MemoryRouter>);
    expect(html).toContain("Lowest -7,870 PLN on 5 Dec (was -6,571 PLN)");
    expect(html).toContain("chart-low flash");
  });

  it("passes each event on once, so a replayed stream does not repeat toasts", () => {
    const known = new Set<string>();
    expect(fixtures.events.map((e) => isNew(e, known))).toEqual([true, true, true, true, true]);
    expect(fixtures.events.some((e) => isNew(e, known))).toBe(false);
  });
});

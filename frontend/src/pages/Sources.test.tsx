import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { resetMockState } from "../api/mock";
import { ago } from "../lib/clock";
import { SourcesView } from "./Sources";

afterEach(resetMockState);
const NOW = Date.parse("2026-11-21T10:14:48Z");

describe("Sources screen", () => {
  it("renders all seven fixture sources across the two companies, KSeF in amber with its error", async () => {
    const all = [...(await api.sources("co_borsuk")).items, ...(await api.sources("co_amalfi")).items];
    const html = renderToStaticMarkup(<SourcesView sources={all} now={NOW} onSync={async () => {}} />);
    expect(html.split('<tr class="source').length - 1).toBe(7);
    const ksef = html.split('<tr class="source').find((row) => row.includes("KSeF"))!;
    expect(ksef).toContain('class="dot degraded"');
    expect(ksef).toContain('class="chip warning"');
    expect(ksef).toContain("Rate limited by KSeF test API, backing off");
    expect(html).toContain("8 s ago");
  });

  it("words elapsed time shortly", () => {
    expect(ago("2026-11-21T10:14:40Z", NOW)).toBe("8 s ago");
    expect(ago("2026-11-21T10:10:00Z", NOW)).toBe("4 min ago");
    expect(ago("2026-11-20T11:30:05Z", NOW)).toBe("22 h ago");
    expect(ago("2026-11-18T10:00:00Z", NOW)).toBe("3 days ago");
    expect(ago("2026-11-21T10:20:00Z", NOW)).toBe("0 s ago");
  });

  it("a manual sync moves 'last synced' forward", async () => {
    const before = (await api.sources("co_borsuk")).items.find((s) => s.id === "src_ksef")!.last_synced_at!;
    const run = await api.syncNow("src_ksef");
    expect(run).toMatchObject({ source_id: "src_ksef", trigger: "manual" });
    const after = (await api.sources("co_borsuk")).items.find((s) => s.id === "src_ksef")!.last_synced_at!;
    expect(Date.parse(after)).toBeGreaterThan(Date.parse(before));
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { api, type ChatAnswer } from "../api/client";
import { ChatView, SUGGESTIONS } from "./Chat";

const render = (turns: { question: string; answer: ChatAnswer }[], suggestions = SUGGESTIONS.co_borsuk) =>
  renderToStaticMarkup(<MemoryRouter><ChatView turns={turns} busy={false} error={null} onSend={() => {}} suggestions={suggestions} /></MemoryRouter>);

describe("Ask Ordo", () => {
  it("offers the suggested questions, including the pizzeria's June closure", () => {
    expect(render([])).toContain("Why will I be short in December?");
    expect(render([], SUGGESTIONS.co_amalfi)).toContain("We are closed for all of June");
  });

  it("shows the answer with evidence chips that open the rows behind it", async () => {
    const answer = await api.chat("Why will I be short?", "co_borsuk");
    const html = render([{ question: "Why will I be short?", answer }]);
    expect(html).toContain(answer.answer);
    expect(html).toContain(`href="${answer.evidence[0].url}"`);
    expect(html).toContain("How I got this");
  });

  it("shows a table, a proposed card and a refusal when the answer carries them", () => {
    const base: ChatAnswer = { session_id: "s", answer: "Here are the three largest.", evidence: [] };
    const table = render([{ question: "q", answer: { ...base, table: { columns: ["Vendor", "Amount"], rows: [["PixelBoard", "180.62 PLN"]], sql: "select 1" } } }]);
    expect(table).toContain("<th>Vendor</th>");
    expect(table).toContain("<td>180.62 PLN</td>");
    const card = render([{ question: "Pay Jan back now.", answer: { ...base, created_recommendation_id: "rec_412" } }]);
    expect(card).toContain('href="/inbox/rec_412"');
    expect(card).toContain("Needs your approval");
    expect(card).toContain("Simulated");
    const refused = render([{ question: "q", answer: { ...base, guardrail: { blocked: true, reason: "I cannot give investment advice." } } }]);
    expect(refused).toContain("I cannot give investment advice.");
    expect(refused).not.toContain("Here are the three largest.");
  });
});

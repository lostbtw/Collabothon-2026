import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HistoryItem } from "./AskOrdo";

const row = (props: Partial<Parameters<typeof HistoryItem>[0]> = {}) =>
  renderToStaticMarkup(
    <HistoryItem title="How much cash do I have?" when="10:14" on={false} confirming={false}
      onOpen={() => {}} onAsk={() => {}} onCancel={() => {}} onDelete={() => {}} {...props} />,
  );

describe("a chat in the history list", () => {
  it("opens with its own button and has a separate delete button named after the chat", () => {
    const html = row();
    expect(html).toContain('class="history-item"');
    expect(html).toContain("How much cash do I have?");
    expect(html).toContain('aria-label="Delete chat “How much cash do I have?”"');
    expect(html).not.toContain("Delete this chat?");
    expect(html.match(/<button/g)).toHaveLength(2);
  });

  it("marks the open chat", () => {
    expect(row({ on: true })).toContain('class="history-row on"');
  });

  it("asks before deleting, in place, with Delete and Cancel", () => {
    const html = row({ confirming: true });
    expect(html).toContain('role="group" aria-label="Delete chat “How much cash do I have?”?"');
    expect(html).toContain("Delete this chat?");
    expect(html).toMatch(/<button type="button" class="delete-confirm"[^>]*>Delete<\/button>/);
    expect(html).toContain(">Cancel</button>");
    expect(html).not.toContain('class="history-item"');
  });

  it("locks both buttons while the chat is being deleted", () => {
    const html = row({ confirming: true, deleting: true });
    expect(html).toContain("Deleting…");
    expect(html.match(/disabled=""/g)).toHaveLength(2);
  });
});

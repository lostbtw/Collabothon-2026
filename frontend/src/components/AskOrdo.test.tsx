import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChatHead, DeleteChatActions, DeleteChatText } from "./AskOrdo";

const head = (onDelete?: () => void) => renderToStaticMarkup(<ChatHead title="How much cash do I have?" onDelete={onDelete} onClose={() => {}} />);

describe("deleting the open chat", () => {
  it("puts a delete icon on the right, before the close button, without a label", () => {
    const html = head(() => {});
    expect(html).toMatch(/<span class="medium conv-title grow"[^>]*>How much cash do I have\?<\/span><button type="button" class="quiet icon-button conv-delete" aria-label="Delete this chat" title="Delete this chat"><svg[^]*?<\/svg><\/button><button[^>]*aria-label="Close"/);
    expect(html).not.toContain(">Delete<");
  });

  it("has no delete button for a new chat that is not saved yet", () => {
    const html = renderToStaticMarkup(<ChatHead title="New chat" onClose={() => {}} />);
    expect(html).toContain("New chat");
    expect(html).not.toContain("conv-delete");
  });

  it("asks with the chat's name and says what stays", () => {
    const html = renderToStaticMarkup(<DeleteChatText title="How much cash do I have?" />);
    expect(html).toContain("“How much cash do I have?” and all its messages will be deleted for this company. This cannot be undone.");
    expect(html).toContain("To-dos the chat added to your list stay there.");
    expect(html).not.toContain('role="alert"');
  });

  it("shows why a delete did not go through", () => {
    const html = renderToStaticMarkup(<DeleteChatText title="x" error="Not deleted: the backend cannot delete chats yet." />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("the backend cannot delete chats yet");
  });

  it("offers Cancel and a red Delete chat, both locked while deleting", () => {
    const idle = renderToStaticMarkup(<DeleteChatActions deleting={false} onCancel={() => {}} onDelete={() => {}} />);
    expect(idle).toMatch(/>Cancel<\/button><button type="button" class="danger-solid">Delete chat<\/button>/);
    const busy = renderToStaticMarkup(<DeleteChatActions deleting onCancel={() => {}} onDelete={() => {}} />);
    expect(busy).toContain("Deleting…");
    expect(busy.match(/disabled=""/g)).toHaveLength(2);
  });
});

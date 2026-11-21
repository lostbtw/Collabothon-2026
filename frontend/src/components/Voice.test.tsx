import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./AskOrdo";
import { HEARD_NOTHING, UNAVAILABLE, VoiceControls, VoiceStatus, type VoiceState } from "./Voice";

const controls = (state: VoiceState, extra: { available?: boolean } = {}) =>
  renderToStaticMarkup(<VoiceControls state={state} available={extra.available} onPress={() => {}} />);
const mic = (html: string) => html.match(/<button[^>]*class="mic[^"]*"[^>]*>/)?.[0] ?? "";
const status = (state: VoiceState) => renderToStaticMarkup(<VoiceStatus state={state} />);

describe("the chat's mic", () => {
  it("waits to be pressed, saying which languages it understands", () => {
    const button = mic(controls({ step: "idle" }));
    expect(button).toContain('type="button"');
    expect(button).toContain('aria-pressed="false"');
    expect(button).toContain('aria-label="Speak your question (Polish, English or Russian)"');
    expect(button).not.toContain("disabled");
    expect(status({ step: "idle" })).toBe("");
  });

  it("shows it is listening, with the time left, and stops on the next press", () => {
    const html = controls({ step: "recording", msLeft: 42_000 });
    expect(mic(html)).toContain('aria-pressed="true"');
    expect(mic(html)).toContain('aria-label="Stop recording"');
    expect(mic(html)).toContain('class="mic on"');
    expect(mic(html)).not.toContain("disabled");
    expect(status({ step: "recording", msLeft: 42_000 })).toContain("Listening · 0:42");
    expect(status({ step: "recording", msLeft: 42_000 })).toContain('role="status"');
  });

  it("can be pressed again while the browser asks for the microphone", () => {
    expect(mic(controls({ step: "asking" }))).toContain('aria-label="Stop waiting for the microphone"');
    expect(status({ step: "asking" })).toContain("Allow the microphone");
  });

  it("is off while Whisper writes the text down", () => {
    expect(mic(controls({ step: "transcribing" }))).toContain('disabled=""');
    expect(status({ step: "transcribing" })).toContain("Writing down what you said");
  });

  it("is off when speech to text is not reachable", () => {
    const button = mic(controls({ step: "idle" }, { available: false }));
    expect(button).toContain('disabled=""');
    expect(button).toContain(`title="${UNAVAILABLE}"`);
  });

  it("has no language switch: Whisper detects the language", () => {
    expect(controls({ step: "idle" })).not.toContain("PL");
    expect(controls({ step: "idle" }).match(/<button/g)).toHaveLength(1);
  });

  it("says what went wrong next to the box", () => {
    const html = status({ step: "error", message: HEARD_NOTHING });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Ordo heard nothing");
  });
});

describe("the chat's message box", () => {
  afterEach(() => vi.unstubAllGlobals());
  const box = (speech: { model: string; reachable: boolean } | null) =>
    renderToStaticMarkup(<Composer busy={false} onSend={() => {}} speech={speech} />);
  const browserCanRecord = () => {
    vi.stubGlobal("MediaRecorder", Object.assign(function () {}, { isTypeSupported: () => true }));
    vi.stubGlobal("navigator", { language: "pl-PL", mediaDevices: { getUserMedia: async () => ({}) } });
  };

  it("has the mic when the browser can record and speech to text is there", () => {
    browserCanRecord();
    const html = box({ model: "turbo", reachable: true });
    expect(mic(html)).toContain('aria-label="Speak your question (Polish, English or Russian)"');
    expect(mic(html)).not.toContain("disabled");
    expect(html).toContain('aria-label="Send"');
  });

  it("shows the mic switched off when speech to text does not answer", () => {
    browserCanRecord();
    expect(mic(box({ model: "turbo", reachable: false }))).toContain('disabled=""');
  });

  it("has no mic without speech to text or without a browser that records", () => {
    browserCanRecord();
    expect(box(null)).not.toContain('class="mic');
    vi.unstubAllGlobals();
    expect(box({ model: "turbo", reachable: true })).not.toContain('class="mic');
  });
});

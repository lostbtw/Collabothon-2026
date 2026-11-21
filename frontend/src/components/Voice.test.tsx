import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HEARD_NOTHING, UNAVAILABLE, VoiceControls, VoiceStatus, type VoiceState } from "./Voice";

const controls = (state: VoiceState, extra: { available?: boolean; language?: "pl" | "en" | "ru" } = {}) =>
  renderToStaticMarkup(<VoiceControls state={state} language={extra.language ?? "pl"} available={extra.available} onPress={() => {}} onLanguage={() => {}} />);
const mic = (html: string) => html.match(/<button[^>]*class="mic[^"]*"[^>]*>/)?.[0] ?? "";
const status = (state: VoiceState) => renderToStaticMarkup(<VoiceStatus state={state} />);

describe("the chat's mic", () => {
  it("waits to be pressed, named for the language the owner speaks", () => {
    const button = mic(controls({ step: "idle" }));
    expect(button).toContain('type="button"');
    expect(button).toContain('aria-pressed="false"');
    expect(button).toContain('aria-label="Speak your question in Polish"');
    expect(button).not.toContain("disabled");
    expect(status({ step: "idle" })).toBe("");
  });

  it("shows it is listening, with the time left, and stops on the next press", () => {
    const html = controls({ step: "recording", msLeft: 42_000 }, { language: "ru" });
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

  it("marks the chosen language and locks the choice while recording", () => {
    const idle = controls({ step: "idle" }, { language: "en" });
    expect(idle).toContain('aria-pressed="true">EN</button>');
    expect(idle).toContain('aria-pressed="false">PL</button>');
    expect(idle).toContain('aria-pressed="false">RU</button>');
    expect(idle).toContain('role="group" aria-label="Language you speak"');
    expect(controls({ step: "recording", msLeft: 1000 })).toMatch(/disabled=""[^>]*>PL<\/button>/);
  });

  it("says what went wrong next to the box", () => {
    const html = status({ step: "error", message: HEARD_NOTHING });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Ordo heard nothing");
  });
});

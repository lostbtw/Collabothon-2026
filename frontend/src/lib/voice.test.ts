import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/transport";
import {
  defaultLanguage, formatLeft, micMessage, pickMimeType, savedLanguage, saveLanguage, startRecording, transcribeMessage, voiceSupported, type VoiceDeps,
} from "./voice";

class FakeRecorder extends EventTarget {
  static supported = new Set(["audio/webm;codecs=opus"]);
  static isTypeSupported = (type: string) => FakeRecorder.supported.has(type);
  static last: FakeRecorder | null = null;
  state: RecordingState = "inactive";
  mimeType: string;

  constructor(public stream: MediaStream, options?: MediaRecorderOptions) {
    super();
    this.mimeType = options?.mimeType ?? "audio/webm";
    FakeRecorder.last = this;
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    queueMicrotask(() => {
      this.dispatchEvent(Object.assign(new Event("dataavailable"), { data: new Blob(["spoken question"], { type: this.mimeType }) }));
      this.dispatchEvent(new Event("stop"));
    });
  }
}

function microphone(fail?: string) {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  const getUserMedia = vi.fn(async () => {
    if (fail) throw new DOMException("refused", fail);
    return stream;
  });
  const deps: VoiceDeps = { MediaRecorder: FakeRecorder as unknown as VoiceDeps["MediaRecorder"], mediaDevices: { getUserMedia } };
  return { track, getUserMedia, deps };
}

afterEach(() => {
  FakeRecorder.supported = new Set(["audio/webm;codecs=opus"]);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("recording format", () => {
  it("takes webm/opus in Chrome, ogg/opus in Firefox, mp4 in Safari, else the browser's default", () => {
    expect(pickMimeType((t) => ["audio/webm;codecs=opus", "audio/ogg;codecs=opus"].includes(t))).toBe("audio/webm;codecs=opus");
    expect(pickMimeType((t) => t === "audio/ogg;codecs=opus")).toBe("audio/ogg;codecs=opus");
    expect(pickMimeType((t) => t === "audio/mp4")).toBe("audio/mp4");
    expect(pickMimeType(() => false)).toBe("");
    expect(pickMimeType(() => { throw new Error("old browser"); })).toBe("");
  });

  it("needs both MediaRecorder and getUserMedia", () => {
    expect(voiceSupported(microphone().deps)).toBe(true);
    expect(voiceSupported({ mediaDevices: microphone().deps.mediaDevices })).toBe(false);
    expect(voiceSupported({ MediaRecorder: microphone().deps.MediaRecorder })).toBe(false);
  });
});

describe("recording", () => {
  it("asks for the microphone only, and gives the recording with its format, then releases the microphone", async () => {
    const { track, getUserMedia, deps } = microphone();
    const recording = await startRecording({}, deps);

    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(FakeRecorder.last?.state).toBe("recording");
    expect(track.stop).not.toHaveBeenCalled();
    recording.stop();
    const blob = await recording.done;

    expect(blob?.type).toBe("audio/webm;codecs=opus");
    expect(await blob?.text()).toBe("spoken question");
    expect(track.stop).toHaveBeenCalledOnce();
  });

  it("records in mp4 where only mp4 works (Safari)", async () => {
    FakeRecorder.supported = new Set(["audio/mp4"]);
    const recording = await startRecording({}, microphone().deps);
    recording.stop();
    expect((await recording.done)?.type).toBe("audio/mp4");
  });

  it("counts down and stops by itself after a minute", async () => {
    vi.useFakeTimers();
    const { track, deps } = microphone();
    const ticks: number[] = [];
    const recording = await startRecording({ onTick: (left) => ticks.push(left) }, deps);

    await vi.advanceTimersByTimeAsync(3000);
    expect(ticks).toEqual([59_000, 58_000, 57_000]);
    expect(FakeRecorder.last?.state).toBe("recording");
    await vi.advanceTimersByTimeAsync(57_000);

    expect((await recording.done)?.type).toBe("audio/webm;codecs=opus");
    expect(track.stop).toHaveBeenCalledOnce();
    const ticked = ticks.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(ticks.length).toBe(ticked);
  });

  it("cancelling throws the recording away and releases the microphone", async () => {
    const { track, deps } = microphone();
    const recording = await startRecording({}, deps);
    recording.cancel();

    expect(await recording.done).toBeNull();
    expect(track.stop).toHaveBeenCalledOnce();
  });

  it("releases the microphone when the recorder cannot start", async () => {
    const { track, deps } = microphone();
    const Broken = Object.assign(function () { throw new DOMException("bad type", "NotSupportedError"); }, { isTypeSupported: () => true });
    await expect(startRecording({}, { ...deps, MediaRecorder: Broken as unknown as VoiceDeps["MediaRecorder"] })).rejects.toMatchObject({ name: "NotSupportedError" });
    expect(track.stop).toHaveBeenCalledOnce();
  });

  it("passes on a refused microphone", async () => {
    await expect(startRecording({}, microphone("NotAllowedError").deps)).rejects.toMatchObject({ name: "NotAllowedError" });
  });

  it("refuses to start without recording support", async () => {
    await expect(startRecording({}, {})).rejects.toMatchObject({ name: "NotSupportedError" });
  });
});

describe("what the owner reads", () => {
  it("shows the time left as m:ss", () => {
    expect(formatLeft(60_000)).toBe("1:00");
    expect(formatLeft(42_000)).toBe("0:42");
    expect(formatLeft(1_500)).toBe("0:02");
    expect(formatLeft(0)).toBe("0:00");
  });

  it("explains each microphone problem", () => {
    expect(micMessage(new DOMException("", "NotAllowedError"))).toMatch(/blocked/);
    expect(micMessage(new DOMException("", "NotFoundError"))).toBe("No microphone found.");
    expect(micMessage(new DOMException("", "NotReadableError"))).toMatch(/busy/);
    expect(micMessage(new DOMException("", "NotSupportedError"))).toMatch(/cannot record/);
    expect(micMessage(new Error("?"))).toMatch(/did not start/);
  });

  it("explains each answer of the speech service", () => {
    expect(transcribeMessage(new ApiError(503, ""))).toMatch(/unavailable/);
    expect(transcribeMessage(new ApiError(413, ""))).toMatch(/too long/);
    expect(transcribeMessage(new ApiError(415, ""))).toMatch(/could not read/);
    expect(transcribeMessage(new ApiError(422, ""))).toMatch(/could not read/);
    expect(transcribeMessage(new TypeError("Failed to fetch"))).toMatch(/did not answer/);
  });
});

describe("language", () => {
  it("starts from the browser's language", () => {
    expect(defaultLanguage("pl-PL")).toBe("pl");
    expect(defaultLanguage("ru")).toBe("ru");
    expect(defaultLanguage("en-US")).toBe("en");
    expect(defaultLanguage("de-DE")).toBe("en");
    expect(defaultLanguage(undefined)).toBe("en");
  });

  it("remembers the owner's choice in this browser", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => store.set(k, v) });
    vi.stubGlobal("navigator", { language: "pl-PL" });

    expect(savedLanguage()).toBe("pl");
    saveLanguage("ru");
    expect(savedLanguage()).toBe("ru");
  });

  it("works without storage", () => {
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
    vi.stubGlobal("navigator", { language: "ru-RU" });

    expect(() => saveLanguage("pl")).not.toThrow();
    expect(savedLanguage()).toBe("ru");
  });
});

// Voice input for the chat: the browser records the owner's question; Whisper on the cluster turns it into text.
import type { SpeechLanguage } from "../api/client";
import { ApiError } from "../api/transport";

export const MAX_RECORDING_MS = 60_000;
export const LANGUAGES: SpeechLanguage[] = ["pl", "en", "ru"];
const LANGUAGE_KEY = "ordo.voiceLanguage";
const TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];

type RecorderClass = { new (stream: MediaStream, options?: MediaRecorderOptions): MediaRecorder; isTypeSupported(type: string): boolean };
export type VoiceDeps = { MediaRecorder?: RecorderClass; mediaDevices?: Pick<MediaDevices, "getUserMedia"> };
export type Recording = { done: Promise<Blob | null>; stop: () => void; cancel: () => void };

const browser = (): VoiceDeps => ({ MediaRecorder: globalThis.MediaRecorder, mediaDevices: globalThis.navigator?.mediaDevices });

export function voiceSupported(deps: VoiceDeps = browser()): boolean {
  return Boolean(deps.MediaRecorder && deps.mediaDevices?.getUserMedia);
}

export function pickMimeType(isTypeSupported: (type: string) => boolean): string {
  return TYPES.find((type) => {
    try {
      return isTypeSupported(type);
    } catch {
      return false;
    }
  }) ?? "";
}

export async function startRecording(
  { maxMs = MAX_RECORDING_MS, onTick }: { maxMs?: number; onTick?: (msLeft: number) => void } = {},
  deps: VoiceDeps = browser(),
): Promise<Recording> {
  const Recorder = deps.MediaRecorder;
  if (!Recorder || !deps.mediaDevices?.getUserMedia) throw new DOMException("This browser cannot record audio", "NotSupportedError");
  const stream = await deps.mediaDevices.getUserMedia({ audio: true });
  const release = () => stream.getTracks().forEach((track) => track.stop());
  let recorder: MediaRecorder;
  try {
    const mimeType = pickMimeType((type) => Recorder.isTypeSupported(type));
    recorder = new Recorder(stream, mimeType ? { mimeType } : undefined);
  } catch (error) {
    release();
    throw error;
  }

  const chunks: Blob[] = [];
  let cancelled = false;
  let left = maxMs;
  const stop = () => {
    if (recorder.state !== "inactive") recorder.stop();
  };
  const ticker = setInterval(() => {
    left = Math.max(0, left - 1000);
    onTick?.(left);
  }, 1000);
  const limit = setTimeout(stop, maxMs);
  const done = new Promise<Blob | null>((resolve) => {
    recorder.addEventListener("dataavailable", (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    });
    recorder.addEventListener("error", stop);
    recorder.addEventListener("stop", () => {
      clearInterval(ticker);
      clearTimeout(limit);
      release();
      resolve(cancelled ? null : new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || "audio/webm" }));
    });
  });
  recorder.start();
  return {
    done,
    stop,
    cancel: () => {
      cancelled = true;
      if (recorder.state === "inactive") {
        clearInterval(ticker);
        clearTimeout(limit);
        release();
      } else recorder.stop();
    },
  };
}

export function formatLeft(ms: number): string {
  const seconds = Math.ceil(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function micMessage(error: unknown): string {
  switch ((error as { name?: string } | null)?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "The microphone is blocked. Allow it for this site in the browser, then try again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No microphone found.";
    case "NotReadableError":
    case "AbortError":
      return "The microphone is busy in another app.";
    case "NotSupportedError":
      return "This browser cannot record audio. Type your question instead.";
    default:
      return "The microphone did not start. Try again.";
  }
}

export function transcribeMessage(error: unknown): string {
  const status = error instanceof ApiError ? error.status : (error as { status?: number } | null)?.status;
  if (status === 503) return "Voice input is unavailable right now. Type your question instead.";
  if (status === 413) return "The recording is too long. Keep it under a minute.";
  if (status === 415 || status === 422) return "Ordo could not read the recording. Try again.";
  return "Voice input did not answer. Try again.";
}

const isLanguage = (value: unknown): value is SpeechLanguage => LANGUAGES.includes(value as SpeechLanguage);

export function defaultLanguage(browserLanguage?: string): SpeechLanguage {
  const code = (browserLanguage ?? "").toLowerCase();
  return code.startsWith("pl") ? "pl" : code.startsWith("ru") ? "ru" : "en";
}

export function savedLanguage(): SpeechLanguage {
  try {
    const saved = globalThis.localStorage?.getItem(LANGUAGE_KEY);
    if (isLanguage(saved)) return saved;
  } catch {
  }
  return defaultLanguage(globalThis.navigator?.language);
}

export function saveLanguage(language: SpeechLanguage): void {
  try {
    globalThis.localStorage?.setItem(LANGUAGE_KEY, language);
  } catch {
  }
}

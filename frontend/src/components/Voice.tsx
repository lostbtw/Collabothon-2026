// The mic of the chat's message box: record, have Whisper write it down, put the text in the box for the owner to check and send.
import { useEffect, useRef, useState } from "react";
import { api, type SpeechLanguage } from "../api/client";
import { LANGUAGES, MAX_RECORDING_MS, formatLeft, micMessage, saveLanguage, savedLanguage, startRecording, transcribeMessage, type Recording } from "../lib/voice";
import { Icon } from "./Icon";

export type VoiceState =
  | { step: "idle" }
  | { step: "asking" }
  | { step: "recording"; msLeft: number }
  | { step: "transcribing" }
  | { step: "error"; message: string };

const NAMES: Record<SpeechLanguage, string> = { pl: "Polish", en: "English", ru: "Russian" };
export const HEARD_NOTHING = "Ordo heard nothing. Try again a little closer to the microphone.";
export const UNAVAILABLE = "Voice input is unavailable right now";

export function useVoice(onText: (text: string) => void) {
  const [state, setState] = useState<VoiceState>({ step: "idle" });
  const [language, setLanguageState] = useState<SpeechLanguage>(savedLanguage);
  const recording = useRef<Recording | null>(null);
  const attempt = useRef(0);
  const deliver = useRef(onText);
  useEffect(() => { deliver.current = onText; });
  useEffect(() => () => {
    attempt.current += 1;
    recording.current?.cancel();
    recording.current = null;
  }, []);

  async function begin(spoken: SpeechLanguage) {
    const id = ++attempt.current;
    const current = () => attempt.current === id;
    setState({ step: "asking" });
    let rec: Recording;
    try {
      rec = await startRecording({ onTick: (msLeft) => current() && setState({ step: "recording", msLeft }) });
    } catch (error) {
      if (current()) setState({ step: "error", message: micMessage(error) });
      return;
    }
    if (!current()) {
      rec.cancel();
      return;
    }
    recording.current = rec;
    setState({ step: "recording", msLeft: MAX_RECORDING_MS });
    const audio = await rec.done;
    recording.current = null;
    if (!current() || !audio) return;
    setState({ step: "transcribing" });
    try {
      const text = (await api.transcribe(audio, spoken)).text.trim();
      if (!current()) return;
      if (text) {
        deliver.current(text);
        setState({ step: "idle" });
      } else setState({ step: "error", message: HEARD_NOTHING });
    } catch (error) {
      if (current()) setState({ step: "error", message: transcribeMessage(error) });
    }
  }

  function press() {
    if (state.step === "recording") recording.current?.stop();
    else if (state.step === "asking") {
      attempt.current += 1;
      setState({ step: "idle" });
    } else if (state.step !== "transcribing") void begin(language);
  }

  function setLanguage(next: SpeechLanguage) {
    setLanguageState(next);
    saveLanguage(next);
  }

  return { state, language, press, setLanguage };
}

export function VoiceControls({ state, language, available = true, onPress, onLanguage }: {
  state: VoiceState; language: SpeechLanguage; available?: boolean; onPress: () => void; onLanguage: (language: SpeechLanguage) => void;
}) {
  const recording = state.step === "recording";
  const busy = recording || state.step === "asking" || state.step === "transcribing";
  const label = recording ? "Stop recording" : state.step === "asking" ? "Stop waiting for the microphone" : `Speak your question in ${NAMES[language]}`;
  return (
    <div className="voice">
      <div className="voice-lang" role="group" aria-label="Language you speak">
        {LANGUAGES.map((l) => (
          <button key={l} type="button" title={NAMES[l]} aria-pressed={l === language} disabled={busy || !available} onClick={() => onLanguage(l)}>{l.toUpperCase()}</button>
        ))}
      </div>
      <button type="button" className={`mic${recording ? " on" : ""}`} aria-pressed={recording} aria-label={label} title={available ? label : UNAVAILABLE}
        disabled={!available || state.step === "transcribing"} onClick={onPress}>
        <Icon name={recording ? "stop" : "mic"} size={18} />
      </button>
    </div>
  );
}

export function VoiceStatus({ state }: { state: VoiceState }) {
  if (state.step === "asking") return <span className="caption t2 voice-status" role="status">Allow the microphone in the browser…</span>;
  if (state.step === "recording") return <span className="caption t2 voice-status" role="status">Listening · {formatLeft(state.msLeft)} · press the mic again to stop</span>;
  if (state.step === "transcribing") return <span className="caption t2 voice-status" role="status">Writing down what you said…</span>;
  if (state.step === "error") return <span className="caption danger voice-status" role="alert">{state.message}</span>;
  return null;
}

#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMPLES="$HERE/whisper-samples"
VOICES_REVISION=e9c8a39444359388adaa94255becb37a5a2b8e51
VOICES_URL="https://huggingface.co/rhasspy/piper-voices/resolve/$VOICES_REVISION"

if ! command -v piper >/dev/null || ! command -v ffmpeg >/dev/null || ! command -v jq >/dev/null; then
  exec nix-shell -p piper-tts ffmpeg jq --run "$(printf '%q ' "${BASH_SOURCE[0]}" "$@")"
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

while read -r language voice; do
  curl -fsSL -o "$work/$language.onnx" "$VOICES_URL/$voice.onnx"
  curl -fsSL -o "$work/$language.onnx.json" "$VOICES_URL/$voice.onnx.json"
done < <(jq -r '.voices | to_entries[] | "\(.key) \(.value)"' "$SAMPLES/samples.json")

while IFS=$'\t' read -r file language text; do
  piper -m "$work/$language.onnx" -c "$work/$language.onnx.json" -f "$work/clip.wav" <<<"$text" 2>/dev/null
  ffmpeg -loglevel error -y -i "$work/clip.wav" -ac 1 -ar 16000 -c:a libopus -b:a 24k \
    -map_metadata -1 -fflags +bitexact -flags:a +bitexact "$SAMPLES/$file"
  seconds="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SAMPLES/$file")"
  printf '%-14s %6s s  %s\n' "$file" "${seconds:0:5}" "$text"
done < <(jq -r '.clips[] | [.file, .language, .text] | @tsv' "$SAMPLES/samples.json")

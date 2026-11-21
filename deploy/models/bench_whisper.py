import json
import os
import re
import statistics
import sys
import tarfile
import time

import httpx

BUDGET_SECONDS = 5.0
LONG_CLIP_SECONDS = 9.0
MAX_WER = 0.2


def normalise(text):
    text = text.lower().replace("ё", "е")
    text = re.sub(r"(?<=\d)[\s  .,](?=\d{3}\b)", "", text)
    return re.findall(r"\w+", text)


def wer(expected, heard):
    want, got = normalise(expected), normalise(heard)
    row = list(range(len(got) + 1))
    for i, word in enumerate(want, 1):
        previous, row[0] = row[0], i
        for j, other in enumerate(got, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (word != other))
    return row[-1] / max(len(want), 1)


def read_samples():
    files = {}
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
        for member in archive:
            if member.isfile():
                files[os.path.basename(member.name)] = archive.extractfile(member).read()
    clips = json.loads(files["samples.json"])["clips"]
    return [dict(clip, audio=files[clip["file"]]) for clip in clips]


class Whisper:
    def __init__(self):
        self.base = os.environ["ORDO_WHISPER_URL"].rstrip("/")
        self.root = self.base.removesuffix("/v1")
        self.client = httpx.Client(timeout=300, headers={"Authorization": f"Bearer {os.environ['ORDO_WHISPER_API_KEY']}"})

    def load(self, model):
        started = time.monotonic()
        response = self.client.post(f"{self.root}/api/ps/{model}")
        if response.status_code not in (201, 409):
            raise RuntimeError(f"loading {model} answered HTTP {response.status_code}: {response.text[:200]}")
        return time.monotonic() - started, response.status_code == 409

    def transcribe(self, model, clip):
        started = time.monotonic()
        response = self.client.post(
            f"{self.base}/audio/transcriptions",
            files={"file": (clip["file"], clip["audio"], "audio/webm")},
            data={"model": model, "language": clip["language"], "response_format": "verbose_json", "temperature": "0"})
        seconds = time.monotonic() - started
        if response.status_code != 200:
            raise RuntimeError(f"{clip['file']} answered HTTP {response.status_code}: {response.text[:200]}")
        body = response.json()
        return seconds, body.get("duration") or 0.0, body["text"].strip()


def bench(whisper, models, clips, runs):
    summary = []
    for model in models:
        load_seconds, was_loaded = whisper.load(model)
        print(f"\n## {model}  (load {'already loaded' if was_loaded else f'{load_seconds:.1f} s'})", flush=True)
        whisper.transcribe(model, clips[0])
        print(f"{'clip':<16}{'lang':<6}{'audio s':>8}{'median s':>10}{'WER':>7}  ok    text")
        failed, worst_long = 0, 0.0
        for clip in clips:
            timings, text, audio = [], "", 0.0
            for _ in range(runs):
                seconds, audio, text = whisper.transcribe(model, clip)
                timings.append(seconds)
            median = statistics.median(timings)
            error = wer(clip["text"], text)
            ok = error <= MAX_WER
            failed += not ok
            if audio >= LONG_CLIP_SECONDS:
                worst_long = max(worst_long, median)
            print(f"{clip['file']:<16}{clip['language']:<6}{audio:>8.1f}{median:>10.2f}{error:>7.2f}  "
                  f"{'pass' if ok else 'FAIL'}  {text}", flush=True)
        summary.append((model, len(clips) - failed, len(clips), worst_long))
    print(f"\n{'model':<46}{'right':>8}{'long clip s':>13}  budget {BUDGET_SECONDS:.0f} s")
    for model, right, total, worst_long in summary:
        budget = "-" if not worst_long else ("meets" if worst_long <= BUDGET_SECONDS else "MISSES")
        print(f"{model:<46}{f'{right}/{total}':>8}{worst_long:>13.2f}  {budget}")
    return 0


def check(whisper, clips):
    model = os.environ["ORDO_WHISPER_MODEL"]
    first = {}
    for clip in clips:
        first.setdefault(clip["language"], clip)
    failed = 0
    for clip in first.values():
        seconds, _, text = whisper.transcribe(model, clip)
        error = wer(clip["text"], text)
        status = "OK  " if error <= MAX_WER else "FAIL"
        failed += status == "FAIL"
        print(f"{status} whisper {clip['language']}: {clip['file']} read as {text!r} in {seconds:.1f} s (WER {error:.2f})")
    return 1 if failed else 0


def main(argv):
    clips = read_samples()
    whisper = Whisper()
    if argv[:1] == ["--check"]:
        return check(whisper, clips)
    runs = 3
    if argv[:1] == ["--runs"]:
        runs, argv = int(argv[1]), argv[2:]
    return bench(whisper, argv or [os.environ["ORDO_WHISPER_MODEL"]], clips, runs)


sys.exit(main(sys.argv[1:]))

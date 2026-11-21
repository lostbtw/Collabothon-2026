"""POST /chat/transcribe and /health's speech field, against a fake Whisper."""
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import contract
from backend.api.app import create_app

MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"
KEY = "test-whisper-key"
AUDIO = b"\x1aE\xdf\xa3SAMPLE-OPUS"
HEARD = "Ile mam gotówki na koncie?"


class FakeWhisper:
    def __init__(self, status=200, error=None):
        self.status, self.error, self.requests = status, error, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.error:
            raise self.error
        if request.url.path == "/health":
            return httpx.Response(self.status, text="OK")
        return httpx.Response(self.status, json={"text": f" {HEARD} ", "language": "pl", "duration": 2.4567})


@pytest.fixture
def whisper_env(monkeypatch):
    monkeypatch.setenv("ORDO_WHISPER_URL", "http://whisper.test:8000/v1")
    monkeypatch.setenv("ORDO_WHISPER_MODEL", MODEL)
    monkeypatch.setenv("ORDO_WHISPER_API_KEY", KEY)


@pytest.fixture
def make_client(db, db_url, whisper_env):
    from backend.db.seed import seed

    seed(db)
    clients = []

    def make(whisper: FakeWhisper) -> TestClient:
        c = TestClient(create_app(database_url=db_url, speech_transport=httpx.MockTransport(whisper)))
        clients.append(c.__enter__())
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def transcribe(c, data=AUDIO, content_type="audio/webm;codecs=opus", language="pl"):
    return c.post("/api/v1/chat/transcribe", files={"file": ("question.webm", data, content_type)},
                  data={"language": language})


def row_counts(db) -> dict[str, int]:
    tables = [r[0] for r in db.execute(
        "select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE'")]
    return {t: db.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables}


def test_the_recording_is_forwarded_to_whisper_unchanged_and_the_text_comes_back(make_client):
    whisper = FakeWhisper()
    response = transcribe(make_client(whisper))

    assert response.status_code == 200, response.text
    body = response.json()
    assert contract.errors(body, contract.response_schema("post", "/chat/transcribe", 200)) == []
    assert (body["text"], body["language"], body["duration_seconds"], body["model"]) == (HEARD, "pl", 2.46, MODEL)
    [sent] = whisper.requests
    assert str(sent.url) == "http://whisper.test:8000/v1/audio/transcriptions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    form = sent.content
    assert AUDIO in form
    assert b"Content-Type: audio/webm;codecs=opus" in form
    for field, value in {"model": MODEL, "language": "pl", "response_format": "verbose_json", "temperature": "0"}.items():
        assert f'name="{field}"\r\n\r\n{value}\r\n'.encode() in form


@pytest.mark.parametrize("kwargs,status,code", [
    ({"language": "de"}, 422, "invalid_request"),
    ({"content_type": "image/png"}, 415, "unsupported_media_type"),
    ({"data": b"x" * (5 * 1024 * 1024 + 1)}, 413, "too_large"),
    ({"data": b""}, 422, "invalid_request"),
], ids=["language de", "not audio", "over 5 MB", "empty"])
def test_a_bad_recording_is_refused_before_whisper_is_asked(make_client, kwargs, status, code):
    whisper = FakeWhisper()
    response = transcribe(make_client(whisper), **kwargs)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert contract.errors(response.json(), contract.response_schema("post", "/chat/transcribe", status)) == []
    assert whisper.requests == []


def test_exactly_5_mb_is_accepted(make_client):
    assert transcribe(make_client(FakeWhisper()), data=b"x" * (5 * 1024 * 1024)).status_code == 200


@pytest.mark.parametrize("whisper", [
    FakeWhisper(status=500),
    FakeWhisper(status=403),
    FakeWhisper(error=httpx.ConnectError("refused")),
    FakeWhisper(error=httpx.ReadTimeout("slow")),
], ids=["whisper 500", "wrong key", "not reachable", "timeout"])
def test_whisper_failing_is_speech_unavailable(make_client, whisper):
    response = transcribe(make_client(whisper))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "speech_unavailable"


def test_without_whisper_deployed_it_is_speech_unavailable(client):
    response = transcribe(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "speech_unavailable"


def test_neither_audio_nor_text_is_stored_or_logged(make_client, db, caplog):
    c = make_client(FakeWhisper())
    before = row_counts(db)

    with caplog.at_level(logging.DEBUG):
        assert transcribe(c).status_code == 200

    db.rollback()
    assert row_counts(db) == before
    assert HEARD not in caplog.text
    assert "SAMPLE-OPUS" not in caplog.text


def test_health_has_no_speech_without_whisper(client):
    assert client.get("/api/v1/health").json()["speech"] is None


@pytest.mark.parametrize("whisper,reachable", [
    (FakeWhisper(), True),
    (FakeWhisper(status=403), False),
    (FakeWhisper(error=httpx.ConnectError("refused")), False),
], ids=["answers", "wrong key", "not reachable"])
def test_health_reports_whether_whisper_answers(make_client, whisper, reachable):
    body = make_client(whisper).get("/api/v1/health").json()

    assert body["speech"] == {"model": MODEL, "reachable": reachable}
    assert contract.errors(body, contract.response_schema("get", "/health", 200)) == []

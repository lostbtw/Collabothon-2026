"""Runtime settings, read from the environment (OpenShift ConfigMap / Secret). No secrets in Git."""
import os

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/ordo"


def database_url() -> str:
    return os.environ.get("ORDO_DATABASE_URL", DEFAULT_DATABASE_URL)


def llm_base_url() -> str:
    """OpenAI-compatible endpoint of the vLLM model served on the team's cluster (hard rule 1: never a hosted API)."""
    return os.environ.get("ORDO_LLM_BASE_URL", "http://localhost:8000/v1")


def llm_model() -> str:
    return os.environ.get("ORDO_LLM_MODEL", "ordo-model")


def sse_replay_fixtures() -> bool:
    """Replay contracts/fixtures/event.json to every new SSE client (skeleton mode). Off on the cluster once real events flow."""
    return os.environ.get("ORDO_SSE_REPLAY_FIXTURES", "1") != "0"

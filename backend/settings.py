"""Runtime settings from the environment (OpenShift ConfigMap / Secret), or from `.env` at the repo root locally."""
import os
import ssl
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/ordo"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
SERVICE_CA_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"


def _load_env_file(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def _first(*names: str, default: str = "") -> str:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    return default


def database_url() -> str:
    return os.environ.get("ORDO_DATABASE_URL", DEFAULT_DATABASE_URL)


def llm_base_url() -> str:
    """OpenAI-compatible endpoint of the vLLM model served on the team's cluster, never a hosted API."""
    return _first("ORDO_LLM_BASE_URL", "LLM_BASE_URL", default="http://localhost:8000/v1")


def llm_model() -> str:
    return _first("ORDO_LLM_MODEL", "LLM_MODEL", default="gpt-oss-20b")


def llm_token() -> str:
    return _first("ORDO_LLM_API_KEY", "LLM_TOKEN", default="EMPTY")


def llm_ca_file() -> str | None:
    if os.environ.get("ORDO_LLM_CA_FILE"):
        return os.environ["ORDO_LLM_CA_FILE"]
    return SERVICE_CA_FILE if Path(SERVICE_CA_FILE).is_file() else None


def llm_verify() -> ssl.SSLContext | bool:
    ca_file = llm_ca_file()
    return ssl.create_default_context(cafile=ca_file) if ca_file else True


def ogx_url() -> str:
    return os.environ.get("ORDO_OGX_URL", "")


def ogx_token() -> str:
    return os.environ.get("ORDO_OGX_API_KEY", "EMPTY")


def ogx_model() -> str:
    return os.environ.get("ORDO_OGX_MODEL", "")


def mcp_url() -> str:
    return os.environ.get("ORDO_MCP_URL", "")


def guardrails_url() -> str:
    return os.environ.get("ORDO_GUARDRAILS_URL", "")


def guardrails_config() -> str:
    return os.environ.get("ORDO_GUARDRAILS_CONFIG", "ordo-chat")


def guardrails_token() -> str:
    return os.environ.get("ORDO_GUARDRAILS_API_KEY") or llm_token()


def whisper_url() -> str:
    """OpenAI-compatible speech-to-text endpoint of Whisper on the team's cluster; empty when it is not deployed."""
    return os.environ.get("ORDO_WHISPER_URL", "")


def whisper_model() -> str:
    return os.environ.get("ORDO_WHISPER_MODEL", "")


def whisper_api_key() -> str:
    return os.environ.get("ORDO_WHISPER_API_KEY", "")


def mcp_allowed_hosts() -> list[str]:
    return [h.strip() for h in os.environ.get("ORDO_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]


def sse_replay_fixtures() -> bool:
    return os.environ.get("ORDO_SSE_REPLAY_FIXTURES", "1") != "0"

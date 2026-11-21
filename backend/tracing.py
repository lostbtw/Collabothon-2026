import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger("ordo.tracing")

HTTP_DEFAULTS = {"MLFLOW_HTTP_REQUEST_MAX_RETRIES": "2", "MLFLOW_HTTP_REQUEST_TIMEOUT": "10"}

_enabled = False


def setup(experiment: str) -> bool:
    global _enabled
    _enabled = False
    uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not uri:
        log.info("tracing off: MLFLOW_TRACKING_URI is not set")
        return False
    for name, value in HTTP_DEFAULTS.items():
        os.environ.setdefault(name, value)
    try:
        import mlflow
        import mlflow.openai

        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment)
        mlflow.openai.autolog()
    except Exception as error:
        log.warning("tracing off: MLflow at %s is not usable: %s: %s", uri, type(error).__name__, error)
        return False
    _enabled = True
    log.info("tracing on: experiment %s at %s", experiment, uri)
    return True


def enabled() -> bool:
    return _enabled


@contextmanager
def span(name: str, inputs: dict[str, Any] | None = None, span_type: str = "CHAIN") -> Iterator[Any]:
    if not _enabled:
        yield None
        return
    import mlflow

    with mlflow.start_span(name=name, span_type=span_type) as current:
        if inputs:
            current.set_inputs(inputs)
        yield current


def outputs(current: Any, value: Any) -> None:
    if current is None:
        return
    try:
        current.set_outputs(value)
    except Exception as error:
        log.warning("tracing: span outputs not recorded: %s", error)


def trace_id() -> str | None:
    if not _enabled:
        return None
    try:
        import mlflow

        return mlflow.get_active_trace_id()
    except Exception as error:
        log.warning("tracing: no trace id: %s", error)
        return None


def tag(**tags: Any) -> None:
    if not _enabled:
        return
    values = {key: str(value) for key, value in tags.items() if value is not None}
    if not values:
        return
    try:
        import mlflow

        mlflow.update_current_trace(tags=values)
    except Exception as error:
        log.warning("tracing: trace tags not recorded: %s", error)

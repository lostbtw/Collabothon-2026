"""contracts/openapi.yaml and contracts/schemas as JSON Schema validators (used by the API and its tests)."""
import json
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
BASE = "https://ordo.sample/contracts/"


@cache
def openapi() -> dict[str, Any]:
    return yaml.safe_load((CONTRACTS / "openapi.yaml").read_text(encoding="utf-8"))


@cache
def registry() -> Registry:
    resources = []
    for path in (CONTRACTS / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema.get("$id", BASE + "schemas/" + path.name), Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _resolve_component(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline '#/components/schemas/X' references, which are relative to openapi.yaml, not to the schema files."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/"):
            node: Any = openapi()
            for part in ref[2:].split("/"):
                node = node[part]
            return _resolve_component(node)
        return {k: _resolve_component(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve_component(v) for v in schema]
    return schema


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    schema = {**_resolve_component(schema), "$id": BASE + "openapi.yaml"}
    return Draft202012Validator(schema, registry=registry())


def response_schema(method: str, path: str, status: int) -> dict[str, Any] | None:
    op = openapi()["paths"][path][method.lower()]
    resp = op["responses"].get(str(status))
    if not resp:
        return None
    content = resp.get("content", {}).get("application/json")
    return content["schema"] if content else None


def request_schema(method: str, path: str) -> dict[str, Any] | None:
    op = openapi()["paths"][path][method.lower()]
    content = op.get("requestBody", {}).get("content", {}).get("application/json")
    return content["schema"] if content else None


def errors(instance: Any, schema: dict[str, Any]) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in _validator(schema).iter_errors(instance)]


def entity_errors(entity: str, doc: dict[str, Any]) -> list[str]:
    """Validation errors of `doc` against contracts/schemas/<entity>.schema.json (empty = valid)."""
    return errors(doc, {"$ref": f"./schemas/{entity}.schema.json"})

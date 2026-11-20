"""Validate a dict against a contract schema. Same JSON Schema subset and rules as
contracts/validate_fixtures.py (stdlib only), packaged as a function for tests."""
import json
import re
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_SCHEMAS: dict = {}
_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict,
          "array": list, "null": type(None)}


def _load(name):
    if name not in _SCHEMAS:
        _SCHEMAS[name] = json.loads((CONTRACTS / "schemas" / name).read_text(encoding="utf-8"))
    return _SCHEMAS[name]


def _resolve(ref, current):
    file, _, frag = ref.partition("#")
    doc = _load(file) if file else _load(current)
    for part in [p for p in frag.split("/") if p]:
        doc = doc[part]
    return doc, (file or current)


def _check(v, sch, cur, path, errs):
    if "$ref" in sch:
        sch, cur = _resolve(sch["$ref"], cur)
    if "oneOf" in sch:
        oks = []
        for sub in sch["oneOf"]:
            e = []
            _check(v, sub, cur, path, e)
            oks.append(not e)
        if sum(oks) != 1:
            errs.append(f"{path}: matches {sum(oks)} of oneOf branches (value {v!r:.60})")
        return
    t = sch.get("type")
    if t and (not isinstance(v, _TYPES[t]) or (t in ("number", "integer") and isinstance(v, bool))):
        errs.append(f"{path}: expected {t}, got {type(v).__name__}")
        return
    if "enum" in sch and v not in sch["enum"]:
        errs.append(f"{path}: {v!r} not in enum")
    if "pattern" in sch and isinstance(v, str) and not re.search(sch["pattern"], v):
        errs.append(f"{path}: {v!r} does not match {sch['pattern']}")
    if isinstance(v, dict):
        for r in sch.get("required", []):
            if r not in v:
                errs.append(f"{path}: missing required '{r}'")
        props, ap = sch.get("properties", {}), sch.get("additionalProperties", True)
        for k, x in v.items():
            if k in props:
                _check(x, props[k], cur, f"{path}.{k}", errs)
            elif ap is False:
                errs.append(f"{path}: unexpected property '{k}'")
    if isinstance(v, list):
        if len(v) < sch.get("minItems", 0):
            errs.append(f"{path}: fewer than {sch['minItems']} items")
        for i, x in enumerate(v):
            if "items" in sch:
                _check(x, sch["items"], cur, f"{path}[{i}]", errs)


def schema_errors(value: dict, schema_name: str) -> list[str]:
    """`schema_name` like "transaction" -> errors against contracts/schemas/transaction.schema.json."""
    name = f"{schema_name}.schema.json"
    errs: list[str] = []
    _check(value, _load(name), name, schema_name, errs)
    return errs


def fixture(name: str) -> list:
    return json.loads((CONTRACTS / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))

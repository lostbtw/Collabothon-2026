#!/usr/bin/env python3
"""Validate every fixture against its JSON Schema. Stdlib only (no jsonschema package needed),
supports the subset of JSON Schema used in contracts/schemas: type, required, properties,
additionalProperties, items, minItems, enum, pattern, minimum/maximum, oneOf, $ref (local files + #/$defs).
Usage: python3 contracts/validate_fixtures.py        (exit code 1 on any error)
Fixture naming: fixtures/<schema_name>.json holds a JSON array of examples for schemas/<schema_name>.schema.json
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).parent; SCHEMAS = {}
def load(name):
    if name not in SCHEMAS: SCHEMAS[name] = json.loads((ROOT / "schemas" / name).read_text())
    return SCHEMAS[name]
def resolve(ref, current):
    file, _, frag = ref.partition("#"); doc = load(file) if file else load(current); cur = file or current
    for part in [p for p in frag.split("/") if p]: doc = doc[part]
    return doc, cur
TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict, "array": list, "null": type(None)}
def check(v, sch, cur, path, errs):
    if "$ref" in sch:
        sch, cur = resolve(sch["$ref"], cur)
    if "oneOf" in sch:
        oks = []
        for sub in sch["oneOf"]:
            e = []; check(v, sub, cur, path, e); oks.append(not e)
        if sum(oks) != 1: errs.append(f"{path}: matches {sum(oks)} of oneOf branches (value {v!r:.60})")
        return
    t = sch.get("type")
    if t:
        if not isinstance(v, TYPES[t]) or (t in ("number", "integer") and isinstance(v, bool)):
            errs.append(f"{path}: expected {t}, got {type(v).__name__}"); return
    if "enum" in sch and v not in sch["enum"]: errs.append(f"{path}: {v!r} not in enum {sch['enum']}")
    if "pattern" in sch and isinstance(v, str) and not re.search(sch["pattern"], v): errs.append(f"{path}: {v!r} does not match {sch['pattern']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in sch and v < sch["minimum"]: errs.append(f"{path}: {v} < minimum")
        if "maximum" in sch and v > sch["maximum"]: errs.append(f"{path}: {v} > maximum")
    if isinstance(v, dict):
        for r in sch.get("required", []):
            if r not in v: errs.append(f"{path}: missing required '{r}'")
        props = sch.get("properties", {}); ap = sch.get("additionalProperties", True)
        for k, x in v.items():
            if k in props: check(x, props[k], cur, f"{path}.{k}", errs)
            elif ap is False: errs.append(f"{path}: unexpected property '{k}'")
            elif isinstance(ap, dict): check(x, ap, cur, f"{path}.{k}", errs)
    if isinstance(v, list):
        if len(v) < sch.get("minItems", 0): errs.append(f"{path}: fewer than {sch['minItems']} items")
        for i, x in enumerate(v):
            if "items" in sch: check(x, sch["items"], cur, f"{path}[{i}]", errs)

total = bad = 0
for fx in sorted((ROOT / "fixtures").glob("*.json")):
    name = fx.stem + ".schema.json"
    if not (ROOT / "schemas" / name).exists(): print(f"SKIP {fx.name} (no schema)"); continue
    items = json.loads(fx.read_text()); assert isinstance(items, list), f"{fx.name} must be a JSON array"
    file_bad = 0
    for i, item in enumerate(items):
        errs = []; check(item, load(name), name, f"{fx.stem}[{i}]", errs); total += 1
        if errs: file_bad += 1; print("\n".join("  ERR " + e for e in errs))
    bad += file_bad
    print(f"{'OK ' if not file_bad else '!! '} {fx.name}: {len(items)} example(s)")
print(f"\n{total} examples checked, {bad} invalid"); sys.exit(1 if bad else 0)

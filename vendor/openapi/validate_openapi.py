"""Offline official OpenAPI 3.1 schema validation; candidate integration module.

Requires the existing jsonschema/referencing packages. No network retrieval,
installation, generated-schema replacement, or hand-written OpenAPI validator.
See README.md for the deliberately bounded local-reference profile.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote

BASE_URI = "https://spec.openapis.org/oas/3.1/schema-base/2025-11-23"
DIALECT_URI = "https://spec.openapis.org/oas/3.1/dialect/2024-11-10"
ROOT = Path(__file__).resolve().parent


def _issue(path, message, kind):
    path = list(path)
    pointer = "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in path)
    return {"path": path, "pointer": pointer or "", "message": message, "kind": kind}


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.exceptions import NoSuchResource

    def deny_network(uri):
        raise NoSuchResource(ref=uri)

    manifest = json.loads((ROOT / "SOURCES.json").read_text(encoding="utf-8"))
    resources = {}
    for asset in manifest["assets"]:
        if not asset["file"].endswith(".json"):
            continue
        raw = (ROOT / asset["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
            raise ValueError("Vendored schema checksum mismatch: " + asset["file"])
        document = json.loads(raw)
        resources[document["$id"]] = document

    # Equivalent URI absolutization only. jsonschema 4.26.0 / referencing's
    # dynamic scope otherwise resolves this relative ref against oas-schema.
    # Downloaded official files remain byte-for-byte unchanged and hash checked.
    wrapper = deepcopy(resources[BASE_URI])
    wrapper["$defs"]["schema"]["properties"]["$schema"]["$ref"] = (
        BASE_URI + "#/$defs/dialect"
    )
    resources[BASE_URI] = wrapper
    registry = Registry(retrieve=deny_network).with_resources(
        (uri, Resource.from_contents(document)) for uri, document in resources.items()
    )
    # JSON Schema 2020-12 format-annotation is intentionally not promoted to
    # full format assertion. Optional format extras are not installed here.
    return Draft202012Validator(wrapper, registry=registry)


def _local_reference_errors(spec):
    """Check same-document refs, without interpreting example data as refs.

    Use referencing's maintained 2020-12 subresource walker for Schema Objects.
    External refs and nested $id are explicitly unsupported by this single-file
    profile and block the build, rather than being silently marked validated.
    """
    from referencing.jsonschema import DRAFT202012

    errors, refs, anchors, object_paths = [], [], {}, {}

    def index_paths(value, path=()):
        if isinstance(value, (dict, list)):
            object_paths[id(value)] = path
        children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
        for key, child in children:
            index_paths(child, path + (key,))

    index_paths(spec)

    def inspect_schema(node):
        if not isinstance(node, dict):
            return
        path = object_paths[id(node)]
        if "$id" in node:
            errors.append(_issue(path + ("$id",), "The offline single-document profile does not support nested $id resources.", "unsupported-reference-profile"))
        for key in ("$anchor", "$dynamicAnchor"):
            if isinstance(node.get(key), str):
                anchor = node[key]
                if anchor in anchors and anchors[anchor] is not node:
                    errors.append(_issue(path + (key,), "Duplicate local anchor: " + anchor, "reference-integrity"))
                anchors[anchor] = node
        for key in ("$ref", "$dynamicRef"):
            if isinstance(node.get(key), str):
                refs.append((path + (key,), node[key], True))
        for child in DRAFT202012.subresources_of(node):
            inspect_schema(child)

    def inspect_oas(node, path=()):
        if isinstance(node, list):
            for i, child in enumerate(node):
                inspect_oas(child, path + (i,))
        elif isinstance(node, dict):
            if isinstance(node.get("$ref"), str):
                refs.append((path + ("$ref",), node["$ref"], False))
            for key, child in node.items():
                if key.startswith("x-") or key in ("example", "value"):
                    continue
                if path == ("components",) and key == "schemas" and isinstance(child, dict):
                    for schema in child.values():
                        inspect_schema(schema)
                elif key == "schema":
                    inspect_schema(child)
                else:
                    inspect_oas(child, path + (key,))

    inspect_oas(spec)
    for path, ref, is_schema in refs:
        if not ref.startswith("#"):
            errors.append(_issue(path, "External references are unsupported by this offline single-document profile: " + ref, "unsupported-reference-profile"))
            continue
        fragment = unquote(ref[1:])
        target = spec
        try:
            if fragment and not fragment.startswith("/"):
                target = anchors[fragment]
            elif fragment:
                for token in fragment[1:].split("/"):
                    # RFC 6901 requires ~0 and ~1; malformed escapes must fail.
                    if "~" in token.replace("~0", "").replace("~1", ""):
                        raise KeyError("invalid JSON Pointer escape")
                    key = token.replace("~1", "/").replace("~0", "~")
                    if isinstance(target, list):
                        if not key.isascii() or not key.isdecimal() or (key.startswith("0") and key != "0"):
                            raise KeyError(key)
                        target = target[int(key)]
                    elif isinstance(target, dict):
                        target = target[key]
                    else:
                        raise KeyError(key)
            if not isinstance(target, dict) and not (is_schema and isinstance(target, bool)):
                raise TypeError("reference target is not an object/schema")
        except (KeyError, IndexError, TypeError, ValueError):
            errors.append(_issue(path, "Unresolved or invalid local reference: " + ref, "reference-integrity"))
    return errors


def validate_spec(spec):
    """Return [] or structured errors with JSON path, pointer, message and kind.

    Missing dependencies/resources or unsupported inputs are blocking errors.
    The caller maps each path to its parsed source location and exits nonzero.
    """
    try:
        validator = _validator()
    except ImportError:
        return [_issue((), "OpenAPI validation requires jsonschema and referencing; dependency approval/setup is required. No validation was performed.", "validator-unavailable")]
    except (OSError, ValueError, KeyError) as exc:
        return [_issue((), "Offline official schema bundle unavailable: " + str(exc), "validator-unavailable")]
    try:
        errors = [_issue(e.absolute_path, e.message, "official-schema") for e in validator.iter_errors(spec)]
    except Exception as exc:
        # Do not dump an entire document/schema in a referencing traceback.
        return [_issue((), "Official schema validation could not complete: " + type(exc).__name__, "validator-failure")]
    # An invalid document may not have the object shapes traversal expects.
    if not errors:
        errors.extend(_local_reference_errors(spec))
    return sorted(errors, key=lambda e: (e["pointer"], e["kind"], e["message"]))


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python validate_openapi.py path/to/openapi.json")
    document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    problems = validate_spec(document)
    print(json.dumps({"valid": not problems, "errors": problems}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(problems))

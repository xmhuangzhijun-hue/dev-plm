"""Compare reviewed and independently generated HTTP contracts.

Normalization handles local schema references, insignificant map/list ordering,
single-value const/enum and nullable type/anyOf spelling. It never copies a
request/response schema, path, status or security requirement into the app.
"""
from __future__ import annotations

from copy import deepcopy
import json

METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
SCHEMA_ANNOTATIONS = frozenset({"title", "description", "example", "examples", "$comment"})


class ContractFormatError(ValueError):
    pass


def _sort_key(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _resolve(document, ref):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ContractFormatError("Only local contract references are supported: " + str(ref))
    current = document
    try:
        for token in ref[2:].split("/"):
            current = current[token.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError) as exc:
        raise ContractFormatError("Unresolved reference: " + ref) from exc
    return current


def normalize_schema(schema, document, stack=()):
    if isinstance(schema, bool):
        return schema
    if not isinstance(schema, dict):
        raise ContractFormatError("A schema must be an object or boolean")
    value = deepcopy(schema)
    if "$ref" in value:
        ref = value.pop("$ref")
        if ref in stack:
            # The candidate has no recursive DTOs. Preserve explicit recursion
            # rather than silently removing it or infinitely expanding it.
            return {"$ref": ref, **value}
        resolved = normalize_schema(_resolve(document, ref), document, (*stack, ref))
        if not value:
            return resolved
        sibling = normalize_schema(value, document, stack)
        if isinstance(resolved, dict) and not any(key in resolved for key in sibling):
            return {**resolved, **sibling}
        return {"allOf": sorted([resolved, sibling], key=_sort_key)}
    output = {}
    for key, child in value.items():
        if key in SCHEMA_ANNOTATIONS or key.startswith("x-"):
            continue
        if key in {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}:
            # These are maps of PROPERTY NAMES: never drop a property called
            # title, description, examples or x-anything.
            output[key] = {name: normalize_schema(item, document, stack) for name, item in child.items()}
        elif key in {"items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems",
                     "contains", "propertyNames", "not", "if", "then", "else", "contentSchema"}:
            output[key] = normalize_schema(child, document, stack)
        elif key in {"allOf", "anyOf", "oneOf", "prefixItems"}:
            normalized = [normalize_schema(item, document, stack) for item in child]
            output[key] = normalized if key == "prefixItems" else sorted(normalized, key=_sort_key)
        elif key in {"required", "enum"}:
            output[key] = sorted(child, key=_sort_key)
        elif key == "type" and isinstance(child, list):
            output[key] = sorted(child)
        else:
            output[key] = child
    if "const" in output:
        output["enum"] = [output.pop("const")]
    alternatives = output.get("anyOf")
    if isinstance(alternatives, list) and len(alternatives) == 2:
        nullable = [item for item in alternatives if item == {"type": "null"}]
        other = [item for item in alternatives if item != {"type": "null"}]
        if (len(nullable) == 1 and len(other) == 1 and isinstance(other[0], dict) and "type" in other[0]
                and not (set(other[0]) & {"not", "if", "then", "else", "allOf", "anyOf", "oneOf"})):
            inner = deepcopy(other[0])
            kinds = inner["type"] if isinstance(inner["type"], list) else [inner["type"]]
            inner["type"] = sorted(set([*kinds, "null"]))
            if "enum" in inner:
                inner["enum"] = sorted([*inner["enum"], None], key=_sort_key)
            # Keep siblings; overlapping validation keywords are not erased.
            siblings = {key: val for key, val in output.items() if key != "anyOf"}
            if not (set(inner) & set(siblings)):
                output = {**inner, **siblings}
    return output


def _object(value, document):
    if isinstance(value, dict) and "$ref" in value:
        return {**_resolve(document, value["$ref"]), **{key: val for key, val in value.items() if key != "$ref"}}
    return value


def _content(content, document):
    result = {}
    for media, entry in content.items():
        item = {}
        if "schema" in entry:
            item["schema"] = normalize_schema(entry["schema"], document)
        if "encoding" in entry:
            item["encoding"] = entry["encoding"]
        result[media] = item
    return result


def _parameters(parameters, document):
    result = {}
    for item in parameters:
        item = _object(item, document)
        name = item["name"].lower() if item["in"] == "header" else item["name"]
        key = item["in"] + ":" + name
        if key in result:
            raise ContractFormatError("Duplicate parameter: " + key)
        entry = {"required": item.get("required", False)}
        if "schema" in item:
            entry["schema"] = normalize_schema(item["schema"], document)
        if "content" in item:
            entry["content"] = _content(item["content"], document)
        for extra in ("style", "explode", "allowReserved", "allowEmptyValue", "deprecated"):
            if extra in item:
                entry[extra] = item[extra]
        result[key] = entry
    return result


def _security(requirements):
    return sorted([{name: sorted(scopes) for name, scopes in alternative.items()} for alternative in requirements], key=_sort_key)


def normalize_contract(document):
    if not str(document.get("openapi", "")).startswith("3.1."):
        raise ContractFormatError("This comparator expects OpenAPI 3.1")
    output = {"openapi": "3.1", "paths": {}, "securitySchemes": {}}
    for name, scheme in document.get("components", {}).get("securitySchemes", {}).items():
        scheme = _object(scheme, document)
        output["securitySchemes"][name] = {key: val for key, val in scheme.items() if key != "description" and not key.startswith("x-")}
    for path, path_item in document.get("paths", {}).items():
        path_item = _object(path_item, document)
        operations = {}
        for method, operation in path_item.items():
            if method not in METHODS:
                continue
            inherited = [_object(item, document) for item in path_item.get("parameters", [])]
            declared = [_object(item, document) for item in operation.get("parameters", [])]
            parameters = {item["in"] + ":" + item["name"]: item for item in inherited}
            parameters.update({item["in"] + ":" + item["name"]: item for item in declared})
            entry = {"operationId": operation.get("operationId"),
                     "parameters": _parameters(parameters.values(), document),
                     "security": _security(operation.get("security", document.get("security", []))),
                     "responses": {}}
            if "requestBody" in operation:
                body = _object(operation["requestBody"], document)
                entry["requestBody"] = {"required": body.get("required", False), "content": _content(body.get("content", {}), document)}
            for status, response in operation.get("responses", {}).items():
                response = _object(response, document)
                normalized = {"content": _content(response.get("content", {}), document)}
                if "headers" in response:
                    normalized["headers"] = {name.lower(): normalize_schema(_object(value, document).get("schema", {}), document) for name, value in response["headers"].items()}
                if "links" in response:
                    normalized["links"] = response["links"]
                entry["responses"][str(status)] = normalized
            operations[method] = entry
        output["paths"][path] = operations
    return output


_MISSING = object()


def compare_contract(reviewed, generated):
    """Return exact behavior-difference paths; [] means normalized agreement."""
    expected, actual = normalize_contract(reviewed), normalize_contract(generated)
    differences = []

    def descend(left, right, path):
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                child_path = path + (key,)
                if key not in left:
                    differences.append({"path": list(child_path), "kind": "unexpected", "actual": right[key]})
                elif key not in right:
                    differences.append({"path": list(child_path), "kind": "missing", "expected": left[key]})
                else:
                    descend(left[key], right[key], child_path)
        elif isinstance(left, list) and isinstance(right, list):
            if left != right:
                differences.append({"path": list(path), "kind": "changed", "expected": left, "actual": right})
        elif left != right:
            differences.append({"path": list(path), "kind": "changed", "expected": left, "actual": right})

    descend(expected, actual, ())
    for difference in differences:
        difference["pointer"] = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in difference["path"])
    return differences

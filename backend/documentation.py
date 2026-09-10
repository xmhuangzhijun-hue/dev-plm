"""Allowlisted documentation sharing, with no route/schema/status generation.

This keeps examples and editorial descriptions in the reviewed contract. Model
types, parameters, required fields, status codes, and authentication come only
from independently written Python routes and Pydantic declarations.
"""
from copy import deepcopy
from fastapi.routing import APIRoute


def _examples(content):
    return {media: {key: deepcopy(entry[key]) for key in ("example", "examples") if key in entry}
            for media, entry in content.items() if "example" in entry or "examples" in entry}


def apply_documentation(app, reviewed):
    info = reviewed.get("info", {})
    for key, attribute in (("title", "title"), ("version", "version"), ("description", "description")):
        if key in info:
            setattr(app, attribute, str(info[key]))
    app.servers = deepcopy(reviewed.get("servers", []))
    app.openapi_tags = deepcopy(reviewed.get("tags", []))
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = route.methods or set()
        if len(methods) != 1:
            continue
        method = next(iter(methods)).lower()
        source = reviewed.get("paths", {}).get(route.path_format, {}).get(method)
        if not isinstance(source, dict):
            continue
        for name in ("summary", "description", "tags"):
            if name in source:
                setattr(route, name, deepcopy(source[name]))
        extra = deepcopy(route.openapi_extra or {})
        extra.update({key: deepcopy(value) for key, value in source.items() if key.startswith("x-")})
        body_examples = _examples(source.get("requestBody", {}).get("content", {}))
        if body_examples and route.body_field is not None:
            extra["requestBody"] = {"content": body_examples}
        allowed_statuses = {str(route.status_code or 200), *(str(code) for code in route.responses)}
        for status, response in source.get("responses", {}).items():
            if str(status) not in allowed_statuses:
                continue  # Documentation cannot add a response status.
            status_key = int(status) if str(status).isdigit() else status
            annotation = route.responses.setdefault(status_key, {})
            if "description" in response:
                annotation["description"] = response["description"]
            examples = _examples(response.get("content", {}))
            if examples:
                existing = annotation.setdefault("content", {})
                for media, values in examples.items():
                    existing.setdefault(media, {}).update(values)
        for location, fields in (("path", route.dependant.path_params), ("query", route.dependant.query_params),
                                 ("header", route.dependant.header_params)):
            annotations = {param.get("name"): param for param in source.get("parameters", []) if param.get("in") == location}
            for field in fields:
                annotation = annotations.get(field.alias)
                if annotation and "examples" in annotation:
                    field.field_info.openapi_examples = deepcopy(annotation["examples"])
        route.openapi_extra = extra
    app.openapi_schema = None

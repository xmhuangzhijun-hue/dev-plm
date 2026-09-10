"""CLI for independently generated schema versus an existing reviewed file."""
from argparse import ArgumentParser
import json
from pathlib import Path

from .protocol import ServiceError
from .routes import create_app
from .schema_diff import compare_contract


class SchemaOnlyServices:
    """Introspection only. It cannot serve requests or persist business data."""
    def __getattr__(self, name):
        raise RuntimeError("Schema-only app cannot execute service operation: " + name)


def schema_app(reviewed=None):
    def unavailable_identity(token):
        raise ServiceError(503, "SERVICE_UNAVAILABLE", "此实例仅用于生成契约。")
    return create_app(SchemaOnlyServices(), unavailable_identity, documentation=reviewed)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("reviewed", type=Path)
    parser.add_argument("--generated-output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reviewed = json.loads(args.reviewed.read_text(encoding="utf-8"))
    # Routes and request/response schemas come exclusively from Python code.
    generated = schema_app(reviewed).openapi()
    differences = compare_contract(reviewed, generated)
    report = {"matches": not differences, "difference_count": len(differences), "differences": differences}
    for path, content in ((args.generated_output, generated), (args.report, report)):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"matches": report["matches"], "difference_count": len(differences),
                      "difference_paths": [item["pointer"] for item in differences[:20]]}, ensure_ascii=True))
    return int(bool(differences))


if __name__ == "__main__":
    raise SystemExit(main())

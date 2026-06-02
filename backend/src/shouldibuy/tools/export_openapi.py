"""Export the OpenAPI schema to a file.

Usage::

    python -m shouldibuy.tools.export_openapi openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shouldibuy.api.main import create_app


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m shouldibuy.tools.export_openapi <path>", file=sys.stderr)
        return 2
    out_path = Path(argv[0])
    app = create_app()
    schema = app.openapi()
    out_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"wrote OpenAPI schema -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Bulk walidacja wszystkich Blueprintów (decyzje #4, #16) — bez regeneracji `.py`.

Iteruje `blueprints/<tenant>/<bp>/v<n>/reactflow.json`, wykonuje:
1. Map RF → IR
2. Apply default_timeout cascade
3. Walidator IR (6 kategorii reguł)

Wynik: report błędów + warningów per Blueprint × wersja.

Wywołanie:
```
uv run python -m scripts.validate_all
uv run python -m scripts.validate_all --tenant <id>
uv run python -m scripts.validate_all --strict   # exit !=0 gdy są warningi
```

Exit code: 0 = OK (lub tylko warningi); >0 = liczba Blueprintów z błędami.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mapper import MapperError, map_reactflow_to_cncfsw
from scripts.regenerate_all import discover_rf_files
from validator import apply_default_timeout, validate

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk validate all Blueprints (multi-tenant).")
    parser.add_argument("--tenant", help="Filtruj per Tenant ID")
    parser.add_argument("--blueprint", help="Filtruj per Blueprint ID (wymaga --tenant)")
    parser.add_argument(
        "--strict", action="store_true", help="Warningi też powodują niezerowy exit"
    )
    args = parser.parse_args()

    if args.blueprint and not args.tenant:
        raise SystemExit("--blueprint wymaga --tenant")

    files = discover_rf_files(tenant=args.tenant, blueprint=args.blueprint)
    if not files:
        print(f"Brak Blueprintów w {REPO_ROOT}/blueprints/")
        return

    error_count = 0
    warning_count = 0
    for rf in files:
        try:
            data = json.loads(rf.read_text("utf-8"))
            wf = map_reactflow_to_cncfsw(data)
            apply_default_timeout(wf)
            rep = validate(wf)
            label = f"{rf.relative_to(REPO_ROOT)}"
            if rep.has_errors:
                error_count += 1
                print(f"✗ {label}: {len(rep.errors)} errors, {len(rep.warnings)} warnings")
                for issue in rep.errors:
                    print(f"    {issue}")
            elif rep.warnings:
                warning_count += 1
                print(f"! {label}: 0 errors, {len(rep.warnings)} warnings")
                for issue in rep.warnings:
                    print(f"    {issue}")
            else:
                print(f"✓ {label}")
        except (MapperError, json.JSONDecodeError, ValueError) as exc:
            error_count += 1
            print(f"✗ {rf.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)

    print(
        json.dumps(
            {
                "blueprints": len(files),
                "errors": error_count,
                "warnings": warning_count,
                "strict": args.strict,
            },
            indent=2,
        )
    )

    if args.strict and warning_count > 0:
        sys.exit(error_count + warning_count)
    sys.exit(error_count)


if __name__ == "__main__":
    main()

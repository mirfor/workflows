"""Bulk regeneracja wszystkich Blueprintów (decyzja #4 — multi-tenant; #17 — idempotency).

Iteruje `blueprints/<tenant>/<bp>/v<n>/reactflow.json`, wywołuje pipeline RF→IR→`.py`+manifest
per Blueprint × wersja. Idempotentne — niezmienione IR (source hash match) NIE regeneruje `.py`.

Wywołanie:
```
uv run python -m scripts.regenerate_all                    # cały repo
uv run python -m scripts.regenerate_all --tenant <id>      # jeden Tenant
uv run python -m scripts.regenerate_all --tenant <id> --blueprint <bp>
```

Exit code: 0 = OK; >0 = liczba Blueprintów które rzuciły walidacyjny error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.regenerate_workflow import regenerate

REPO_ROOT = Path(__file__).resolve().parents[1]
BLUEPRINTS_DIR = REPO_ROOT / "blueprints"


def discover_rf_files(tenant: str | None = None, blueprint: str | None = None) -> list[Path]:
    """Znajdź wszystkie `reactflow.json` w layoutcie multi-tenant."""
    rf_files: list[Path] = []
    if not BLUEPRINTS_DIR.exists():
        return rf_files

    tenant_dirs = (
        [BLUEPRINTS_DIR / tenant] if tenant else [d for d in BLUEPRINTS_DIR.iterdir() if d.is_dir()]
    )
    for tdir in tenant_dirs:
        if not tdir.is_dir():
            continue
        bp_dirs = (
            [tdir / blueprint]
            if blueprint
            else [d for d in tdir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        )
        for bp_dir in bp_dirs:
            if not bp_dir.is_dir():
                continue
            for v_dir in sorted(bp_dir.iterdir()):
                if v_dir.is_dir() and v_dir.name.startswith("v"):
                    rf = v_dir / "reactflow.json"
                    if rf.exists():
                        rf_files.append(rf)
    return rf_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk regenerate all Blueprints (multi-tenant).")
    parser.add_argument("--tenant", help="Filtruj per Tenant ID")
    parser.add_argument("--blueprint", help="Filtruj per Blueprint ID (wymaga --tenant)")
    parser.add_argument("--no-activate", action="store_true", help="Skip activation in manifest")
    args = parser.parse_args()

    if args.blueprint and not args.tenant:
        raise SystemExit("--blueprint wymaga --tenant")

    files = discover_rf_files(tenant=args.tenant, blueprint=args.blueprint)
    if not files:
        print(f"Brak Blueprintów w {BLUEPRINTS_DIR}/{args.tenant or '*'}/{args.blueprint or '*'}/")
        return

    failures: list[tuple[Path, str]] = []
    successes: list[dict] = []
    for rf in files:
        try:
            result = regenerate(rf, activate=not args.no_activate)
            successes.append(result)
            print(
                f"✓ {result['tenant_id']}/{result['blueprint_id']} v{result['version']} "
                f"hash={result['source_hash'][:16]}..."
            )
        except SystemExit as exc:
            failures.append((rf, str(exc)))
            print(f"✗ {rf}: {exc}", file=sys.stderr)
        except Exception as exc:
            failures.append((rf, repr(exc)))
            print(f"✗ {rf}: {exc!r}", file=sys.stderr)

    print(
        json.dumps(
            {
                "ok": len(successes),
                "failed": len(failures),
                "tenant_filter": args.tenant,
                "blueprint_filter": args.blueprint,
            },
            indent=2,
        )
    )

    sys.exit(len(failures))


if __name__ == "__main__":
    main()

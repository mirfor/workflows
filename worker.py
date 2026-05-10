"""Temporal Worker startup per Tenant — ładuje active wygenerowane workflows + activities.

Decyzje:
- #4 / ADR-006: Worker per Tenant namespace (osobny deploy + osobny manifest).
- #14 / #17 / ADR-005: Worker importuje tylko `active_version` z `generated/<tenant>/manifest.json`;
  Build ID = sha krótki commit-a (CI ustala).
- #15: Workflow Sandbox passthrough_modules dla `activities` (workflow code importuje fully-qualified
  function references) i `jq` (compiled JQ programs używane w `_eval()`).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from activities import ALL_ACTIVITIES

logger = logging.getLogger("worker")

REPO_ROOT = Path(__file__).resolve().parent


def _manifest_path(tenant_id: str) -> Path:
    return REPO_ROOT / "generated" / tenant_id / "manifest.json"


def _load_active_workflow_classes(tenant_id: str) -> list[type]:
    """Wczytaj `active_version` per Blueprint dla podanego Tenanta (decyzja #4 + #17)."""
    manifest_path = _manifest_path(tenant_id)
    if not manifest_path.exists():
        logger.warning("Brak %s — Worker startuje bez workflows.", manifest_path)
        return []

    manifest: dict[str, Any] = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("tenant_id") and manifest["tenant_id"] != tenant_id:
        raise RuntimeError(
            f"Manifest tenant_id mismatch: file={manifest['tenant_id']!r}, requested={tenant_id!r}"
        )

    classes: list[type] = []
    for blueprint_id, info in manifest.get("blueprints", {}).items():
        active = info.get("active_version")
        if not active:
            continue
        version_info = info.get("versions", {}).get(active)
        if not version_info:
            logger.warning("Manifest: brak entry dla %s v%s", blueprint_id, active)
            continue
        file_path = REPO_ROOT / version_info["file_path"]
        class_name = version_info["class_name"]
        if not file_path.exists():
            logger.error("Brak pliku %s referowanego przez manifest.", file_path)
            continue

        # Pełen dotted name żeby Workflow Sandbox umiał re-importować moduł.
        module_name = f"generated.{tenant_id}.workflows.{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            logger.error("Nie udało się załadować spec dla %s.", file_path)
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module  # CRITICAL — sandbox re-import po name
        spec.loader.exec_module(module)
        cls = getattr(module, class_name, None)
        if cls is None:
            logger.error("Klasa %s nie istnieje w %s.", class_name, file_path)
            continue
        classes.append(cls)
        logger.info(
            "Załadowano workflow %s/%s v%s (class=%s)", tenant_id, blueprint_id, active, class_name
        )

    return classes


async def run_worker(
    *,
    tenant_id: str,
    target_url: str,
    namespace: str,
    task_queue: str,
    build_id: str | None = None,
) -> None:
    client = await Client.connect(target_url, namespace=namespace)
    workflow_classes = _load_active_workflow_classes(tenant_id)

    sandbox_restrictions = SandboxRestrictions.default.with_passthrough_modules(
        "activities",
        "jq",
    )

    worker_kwargs: dict[str, Any] = {
        "task_queue": task_queue,
        "workflows": workflow_classes,
        "activities": ALL_ACTIVITIES,
        "workflow_runner": SandboxedWorkflowRunner(restrictions=sandbox_restrictions),
    }
    if build_id:
        worker_kwargs["build_id"] = build_id

    worker = Worker(client, **worker_kwargs)
    logger.info(
        "Worker startuje: tenant=%s target=%s namespace=%s queue=%s "
        "workflows=%d activities=%d build_id=%s",
        tenant_id,
        target_url,
        namespace,
        task_queue,
        len(workflow_classes),
        len(ALL_ACTIVITIES),
        build_id,
    )
    await worker.run()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser(description="Workflow Platform Temporal Worker (per Tenant)")
    parser.add_argument(
        "--tenant",
        required=True,
        help="Tenant ID — manifest ładowany z generated/<tenant>/manifest.json (decyzja #4)",
    )
    parser.add_argument("--target", default=os.environ.get("TEMPORAL_TARGET", "localhost:7233"))
    parser.add_argument(
        "--namespace",
        default=os.environ.get("TEMPORAL_NAMESPACE"),
        help="Temporal namespace (jeśli pusty — używa --tenant jako namespace per #4 fizyczna izolacja)",
    )
    parser.add_argument(
        "--task-queue",
        default=os.environ.get("TEMPORAL_TASK_QUEUE"),
        help="Task queue (default: weaver-<tenant>)",
    )
    parser.add_argument("--build-id", default=os.environ.get("TEMPORAL_BUILD_ID"))
    args = parser.parse_args()

    namespace = args.namespace or args.tenant
    task_queue = args.task_queue or f"weaver-{args.tenant}"

    asyncio.run(
        run_worker(
            tenant_id=args.tenant,
            target_url=args.target,
            namespace=namespace,
            task_queue=task_queue,
            build_id=args.build_id,
        )
    )


if __name__ == "__main__":
    main()

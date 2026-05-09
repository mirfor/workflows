"""Temporal Worker startup — ładuje wygenerowane workflows + activities.

Decyzje:
- #14 / #17 / ADR-005: Worker importuje wszystkie `generated/workflows/<id>__v<n>.py`
  i rejestruje workflow classes z manifest. Build ID = sha krótki commit-a (CI ustala).
- #4 / ADR-006: Worker działa per Tenant namespace; namespace przekazany przez `--namespace`
  lub env `TEMPORAL_NAMESPACE`.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from activities import ALL_ACTIVITIES

logger = logging.getLogger("worker")

REPO_ROOT = Path(__file__).resolve().parent
GENERATED_DIR = REPO_ROOT / "generated" / "workflows"
MANIFEST_PATH = REPO_ROOT / "generated" / "manifest.json"


def _load_active_workflow_classes() -> list[type]:
    """Wczytaj wygenerowane `.py` per Blueprint × wersja, zwróć aktywne klasy.

    Worker image zawiera tylko latest version per Blueprint (decyzja #17), ale lokalnie
    podczas dev wszystkie wersje zostają na dysku — wczytujemy wyłącznie `active_version`
    z manifestu żeby zminimalizować startup time + ryzyko konfliktu nazw.
    """
    if not MANIFEST_PATH.exists():
        logger.warning("Brak %s — Worker startuje bez workflows.", MANIFEST_PATH)
        return []

    manifest: dict[str, Any] = json.loads(MANIFEST_PATH.read_text("utf-8"))
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

        spec = importlib.util.spec_from_file_location(
            f"generated_workflow_{blueprint_id}_v{active}", file_path
        )
        if spec is None or spec.loader is None:
            logger.error("Nie udało się załadować spec dla %s.", file_path)
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = getattr(module, class_name, None)
        if cls is None:
            logger.error("Klasa %s nie istnieje w %s.", class_name, file_path)
            continue
        classes.append(cls)
        logger.info("Załadowano workflow %s v%s (class=%s)", blueprint_id, active, class_name)

    return classes


async def run_worker(
    target_url: str,
    namespace: str,
    task_queue: str,
    build_id: str | None = None,
) -> None:
    client = await Client.connect(target_url, namespace=namespace)
    workflow_classes = _load_active_workflow_classes()

    worker_kwargs: dict[str, Any] = {
        "task_queue": task_queue,
        "workflows": workflow_classes,
        "activities": ALL_ACTIVITIES,
    }
    if build_id:
        worker_kwargs["build_id"] = build_id

    worker = Worker(client, **worker_kwargs)
    logger.info(
        "Worker startuje: target=%s namespace=%s queue=%s workflows=%d activities=%d build_id=%s",
        target_url, namespace, task_queue, len(workflow_classes), len(ALL_ACTIVITIES), build_id,
    )
    await worker.run()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser(description="Workflow Platform Temporal Worker")
    parser.add_argument("--target", default=os.environ.get("TEMPORAL_TARGET", "localhost:7233"))
    parser.add_argument("--namespace", default=os.environ.get("TEMPORAL_NAMESPACE", "default"))
    parser.add_argument("--task-queue", default=os.environ.get("TEMPORAL_TASK_QUEUE", "weaver-default"))
    parser.add_argument("--build-id", default=os.environ.get("TEMPORAL_BUILD_ID"))
    args = parser.parse_args()
    asyncio.run(run_worker(args.target, args.namespace, args.task_queue, args.build_id))


if __name__ == "__main__":
    main()

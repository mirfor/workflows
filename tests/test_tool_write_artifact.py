"""Tests for `activities.tools.write_artifact`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from activities.tools import write_artifact as wa


@pytest.fixture(autouse=True)
def _isolate_artifact_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wa, "_ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(wa, "_PUBLIC_BASE", "file:///tmp/artifacts")


async def test_write_json(tmp_path: Path) -> None:
    out = await wa.write_artifact(
        {
            "tenant_id": "demo",
            "engagement_id": "eng-1",
            "filename": "postings",
            "format": "json",
            "data": {"hello": "world", "count": 2},
        }
    )
    assert out["format"] == "json"
    assert out["bytes"] > 0
    path = Path(out["absolute_path"])
    assert path.exists()
    assert path.name == "postings.json"
    assert json.loads(path.read_text()) == {"hello": "world", "count": 2}
    assert out["artifact_url"].endswith("/demo/eng-1/postings.json")


async def test_write_csv() -> None:
    out = await wa.write_artifact(
        {
            "tenant_id": "demo",
            "engagement_id": "eng-1",
            "filename": "postings.csv",
            "format": "csv",
            "data": [
                {"nip": "1234567890", "net": 100.0, "vat": 23.0},
                {"nip": "9999999999", "net": 50.0, "vat": 11.5},
            ],
        }
    )
    path = Path(out["absolute_path"])
    content = path.read_text()
    lines = content.strip().splitlines()
    assert lines[0] == "nip,net,vat"
    assert lines[1] == "1234567890,100.0,23.0"
    assert lines[2] == "9999999999,50.0,11.5"


async def test_csv_requires_list_of_dicts() -> None:
    from temporalio.exceptions import ApplicationError

    with pytest.raises(ApplicationError):
        await wa.write_artifact(
            {
                "tenant_id": "demo",
                "engagement_id": "eng-1",
                "filename": "bad.csv",
                "format": "csv",
                "data": "not a list",
            }
        )


async def test_filename_sanitized() -> None:
    out = await wa.write_artifact(
        {
            "tenant_id": "../etc",
            "engagement_id": "eng/1",
            "filename": "../../passwd",
            "format": "json",
            "data": [1, 2, 3],
        }
    )
    path = Path(out["absolute_path"])
    assert "/etc/passwd" not in str(path)
    assert "passwd.json" in path.name

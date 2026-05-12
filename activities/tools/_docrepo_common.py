"""Shared helpers for `docrepo_upload` / `docrepo_download` activities.

Module name starts with `_` so the registry auto-discovery skips it.
"""

from __future__ import annotations

import os

import httpx
from temporalio.exceptions import ApplicationError

DOCREPO_BASE = os.environ.get("DOCREPO_BASE_URL", "http://localhost:8080/api/v1")
DOCREPO_JWT_ENV = "DOCREPO_JWT"


def auth_headers() -> dict[str, str]:
    token = os.environ.get(DOCREPO_JWT_ENV)
    if not token:
        raise ApplicationError(
            f"Missing {DOCREPO_JWT_ENV} env var",
            type="AuthError",
            non_retryable=True,
        )
    return {"Authorization": f"Bearer {token}"}


def raise_for_status(resp: httpx.Response, op: str) -> None:
    if resp.status_code in (401, 403):
        raise ApplicationError(f"{op}: {resp.text}", type="AuthError", non_retryable=True)
    if resp.status_code == 404:
        raise ApplicationError(f"{op}: {resp.text}", type="NotFoundError", non_retryable=True)
    if 400 <= resp.status_code < 500:
        raise ApplicationError(f"{op}: {resp.text}", type="ValidationError", non_retryable=True)
    if resp.status_code >= 500:
        raise ApplicationError(f"{op}: {resp.text}", type="IntegrationError", non_retryable=False)

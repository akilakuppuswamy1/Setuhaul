"""Shared HTTP helpers for SetuHaul live E2E scripts."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("SETUHAUL_API_URL", "http://127.0.0.1:8010").rstrip("/")


def request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def require_health() -> dict[str, Any]:
    code, health = request("GET", "/health")
    if code != 200 or health.get("service") != "setuhaul":
        raise SystemExit(f"SetuHaul API unhealthy at {BASE}: HTTP {code} {health}")
    return health


def list_shipments(page_size: int = 100) -> list[dict[str, Any]]:
    code, payload = request("GET", f"/shipments?page=1&page_size={page_size}")
    if code != 200:
        raise SystemExit(f"list shipments failed HTTP {code}: {payload}")
    return list(payload.get("items") or [])


def resolve_shipment(
    shipment_number: str,
    *,
    hint: str = "python scripts/seed_e2e_fixtures.py",
) -> dict[str, Any]:
    for item in list_shipments():
        if item.get("shipment_number") == shipment_number:
            return item
    raise SystemExit(
        f"Required fixture shipment {shipment_number!r} was not found via GET /shipments. "
        f"Run {hint} against the same database the API uses."
    )


def resolve_driver_by_external_id(
    external_id: str,
    *,
    hint: str = "python scripts/seed_ops_demo.py",
) -> dict[str, Any]:
    code, payload = request("GET", "/drivers?page=1&page_size=200")
    if code != 200:
        raise SystemExit(f"list drivers failed HTTP {code}: {payload}")
    for item in payload.get("items") or []:
        if item.get("external_id") == external_id:
            return item
    raise SystemExit(
        f"Required driver external_id {external_id!r} was not found via GET /drivers. "
        f"Run {hint}."
    )

"""Explicitly apply the selected RU/EN defaults to a running local app through its API."""
from __future__ import annotations

import argparse
import json
from urllib.parse import urlsplit

import httpx

from backend.catalog_defaults import load_manifest, mark_initialized, plan_catalog_changes, canonical_catalog_url


def apply_to_running_app(base_url: str) -> dict:
    base = urlsplit(base_url)
    if base.scheme != "http" or base.hostname not in {"127.0.0.1", "localhost"} or base.path not in {"", "/"}:
        raise ValueError("Укажите локальный HTTP-адрес Переплёта")
    manifest = load_manifest()
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=10) as client:
        session = client.get("/api/session")
        session.raise_for_status()
        client.headers.update({"X-Pereplet": "1", "X-Pereplet-Token": session.json()["token"]})
        response = client.get("/api/catalogs")
        response.raise_for_status()
        before = response.json()
        plan = plan_catalog_changes(before, manifest)
        added = []
        for item in plan["additions"]:
            response = client.post("/api/catalogs", json=item)
            response.raise_for_status()
            added.append(response.json())
        for catalog in plan["removals"]:
            response = client.delete(f"/api/catalogs/{catalog['id']}")
            response.raise_for_status()
        response = client.get("/api/catalogs")
        response.raise_for_status()
        after = response.json()
    expected_preserved = {item["id"]: item for item in before if item not in plan["removals"]}
    actual_by_id = {item["id"]: item for item in after}
    if any(actual_by_id.get(key) != value for key, value in expected_preserved.items()):
        raise RuntimeError("Существующий каталог неожиданно изменился")
    urls = [canonical_catalog_url(item["url"]) for item in after]
    if any(canonical_catalog_url(item["url"]) not in urls for item in added):
        raise RuntimeError("Добавленный каталог отсутствует после сохранения")
    mark_initialized(manifest)
    return {"added": [{"name": item["name"], "url": item["url"]} for item in added],
            "removed": [{"name": item["name"], "url": item["url"]} for item in plan["removals"]],
            "total": len(after), "preserved_existing": len(expected_preserved)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18765")
    args = parser.parse_args()
    print(json.dumps(apply_to_running_app(args.base_url), ensure_ascii=True, indent=2))

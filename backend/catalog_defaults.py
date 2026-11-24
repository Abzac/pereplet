"""One-time catalog defaults. Later user removals and custom entries are preserved."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import library

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "catalog-defaults.json"
MARKER_NAME = "catalog-defaults-initialized.json"


def load_manifest(path: Path | None = None) -> dict:
    return json.loads((path or MANIFEST_PATH).read_text(encoding="utf-8"))


def canonical_catalog_url(value: str) -> str:
    url = urlsplit(value.strip())
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("Неверный адрес каталога")
    host = url.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = url.port
    if port and port != (443 if url.scheme == "https" else 80):
        host += f":{port}"
    path = re.sub(r"%[\da-f]{2}", lambda match: match.group().upper(), url.path, flags=re.I).rstrip("/") or "/"
    return urlunsplit((url.scheme, host, path, url.query, ""))


def plan_catalog_changes(existing: list[dict], manifest: dict) -> dict:
    remove_urls = {canonical_catalog_url(url) for url in manifest.get("remove_known_urls", [])}
    removals = [catalog for catalog in existing if canonical_catalog_url(catalog["url"]) in remove_urls]
    remaining = {canonical_catalog_url(catalog["url"]) for catalog in existing if catalog not in removals}
    additions = []
    for catalog in manifest["catalogs"]:
        variants = {canonical_catalog_url(url) for url in [catalog["url"], *catalog.get("aliases", [])]}
        if remaining.isdisjoint(variants):
            additions.append({"name": catalog["name"], "url": catalog["url"]})
        remaining.update(variants)
    return {"additions": additions, "removals": removals}


def mark_initialized(manifest: dict, *, data_dir: Path | None = None) -> None:
    directory = data_dir or library.DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / MARKER_NAME
    temporary = marker.with_suffix(".tmp")
    state = {"version": manifest["version"], "applied_at": library.now(), "keys": [entry["key"] for entry in manifest["catalogs"]]}
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(marker)


def seed_catalogs() -> dict:
    library.init()
    # Do not re-add deleted defaults, including after a future manifest revision.
    # Changes for an established library must be an explicit migration.
    if (library.DATA_DIR / MARKER_NAME).is_file():
        return {"seeded": False, "reason": "already_initialized"}
    manifest = load_manifest()
    plan = plan_catalog_changes(library.list_catalogs(), manifest)
    added = [library.add_catalog(item) for item in plan["additions"]]
    for catalog in plan["removals"]:
        library.delete_catalog(catalog["id"])
    mark_initialized(manifest)
    return {"seeded": True, "added": added, "removed": plan["removals"]}

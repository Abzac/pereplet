import json

import httpx

from backend import catalog_defaults, library
import update_catalogs


def manifest():
    return {"version": 1, "catalogs": [
        {"key": "one", "name": "Default one", "url": "https://books.example/opds/", "aliases": ["http://books.example/opds/"]},
        {"key": "two", "name": "Default two", "url": "https://other.example/catalog"},
    ], "remove_known_urls": ["https://wolnelektury.pl/opds/"]}


def test_plan_deduplicates_canonical_urls_and_preserves_custom_catalogs():
    existing = [
        {"id": "existing", "name": "My preferred name", "url": "http://BOOKS.example:80/opds/#top"},
        {"id": "custom", "name": "Custom", "url": "http://127.0.0.1:8080/custom"},
        {"id": "polish", "name": "Wolne Lektury", "url": "https://wolnelektury.pl/opds/"},
        {"id": "other-polish", "name": "Custom feed at same host", "url": "https://wolnelektury.pl/my-custom-feed/"},
    ]
    before = json.dumps(existing)
    plan = catalog_defaults.plan_catalog_changes(existing, manifest())
    assert plan["additions"] == [{"name": "Default two", "url": "https://other.example/catalog"}]
    assert [item["id"] for item in plan["removals"]] == ["polish"]
    assert json.dumps(existing) == before


def test_one_time_seed_does_not_resurrect_deleted_defaults_or_replace_custom_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    monkeypatch.setattr(catalog_defaults, "load_manifest", manifest)
    custom = library.add_catalog({"name": "My collection", "url": "http://localhost:9000/opds"})
    library.add_catalog({"name": "Wolne Lektury", "url": "https://wolnelektury.pl/opds/"})
    first = catalog_defaults.seed_catalogs()
    assert first["seeded"] is True
    assert len(first["added"]) == 2
    assert len(first["removed"]) == 1
    library.delete_catalog(first["added"][0]["id"])
    second = catalog_defaults.seed_catalogs()
    assert second["seeded"] is False
    rows = library.list_catalogs()
    assert len(rows) == 2
    assert next(item for item in rows if item["id"] == custom["id"]) == custom
    assert not any(item["id"] == first["added"][0]["id"] for item in rows)
    assert (tmp_path / catalog_defaults.MARKER_NAME).is_file()


def test_explicit_api_migration_preserves_existing_and_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    monkeypatch.setattr(update_catalogs, "load_manifest", manifest)
    catalogs = [
        {"id": "custom", "name": "Local", "url": "http://localhost:9000/opds", "added_at": "old"},
        {"id": "polish", "name": "Wolne", "url": "https://wolnelektury.pl/opds/", "added_at": "old"},
    ]
    writes = []
    def handler(request):
        nonlocal catalogs
        if request.url.path == '/api/session':
            return httpx.Response(200, json={"token": "fixture-token"})
        if request.method == 'GET':
            return httpx.Response(200, json=catalogs)
        assert request.headers['X-Pereplet-Token'] == 'fixture-token'
        writes.append((request.method, request.url.path))
        if request.method == 'POST':
            item = {**json.loads(request.content), "id": f"new-{len(writes)}", "added_at": "new"}
            catalogs.append(item)
            return httpx.Response(200, json=item)
        catalogs = [item for item in catalogs if item['id'] != request.url.path.rsplit('/', 1)[-1]]
        return httpx.Response(200, json={"ok": True})
    real = httpx.Client
    monkeypatch.setattr(update_catalogs.httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    first = update_catalogs.apply_to_running_app('http://127.0.0.1:18765')
    assert len(first['added']) == 2 and len(first['removed']) == 1
    assert catalogs[0] == {"id": "custom", "name": "Local", "url": "http://localhost:9000/opds", "added_at": "old"}
    second = update_catalogs.apply_to_running_app('http://127.0.0.1:18765')
    assert second['added'] == [] and second['removed'] == []
    assert len(writes) == 3
    assert (tmp_path / catalog_defaults.MARKER_NAME).is_file()

"""Integration contract for the metadata features imported from sayfarin."""

import json
from types import SimpleNamespace

from starlette.testclient import TestClient

from mcp_1c77 import tools, web


def test_explorer_and_rest_routes(monkeypatch):
    monkeypatch.setattr(web.tools, "get_loader", lambda: SimpleNamespace(is_loaded=False))
    monkeypatch.setattr(web.tools, "list_objects", lambda kind: "## Документы (1)\n  - АктУслуги")
    monkeypatch.setattr(web.tools, "export_to_json", lambda: json.dumps({"name": "Демо"}))

    client = TestClient(web.app, base_url="http://localhost")
    assert client.get("/explorer").status_code == 200
    assert "Metadata" in client.get("/explorer").text
    assert client.get("/api").json()["tools_count"] == 26
    assert client.get("/api/objects").json()["objects"]["Документ"] == ["АктУслуги"]
    assert client.get("/api/export").json()["data"]["name"] == "Демо"
    assert client.get("/api/export?save=true").status_code == 400
    assert client.get("/api", headers={"Host": "evil.test"}).status_code == 403


def test_export_file_is_confined_to_data_dir(monkeypatch, tmp_path):
    config = SimpleNamespace(model_dump=lambda **kwargs: {"name": "Демо"})
    monkeypatch.setattr(tools, "_loader", SimpleNamespace(is_loaded=True, config=config))
    monkeypatch.setattr(tools, "_data_dir", tmp_path)

    assert "MCP_DATA_DIR" in tools.export_to_json("../outside.json")
    assert "MCP_DATA_DIR" in tools.export_to_json("1cv7.md")
    assert not (tmp_path.parent / "outside.json").exists()
    assert "экспортирована" in tools.export_to_json("config.json")
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["name"] == "Демо"

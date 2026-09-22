"""HTTP contract and local-only mutation protections."""

from pathlib import Path

from starlette.testclient import TestClient

from mcp_1c77 import web


def client(host="127.0.0.1"):
    return TestClient(web.app, base_url="http://localhost", client=(host, 50000))


def test_remote_peer_cannot_mutate_database(monkeypatch, tmp_path):
    called = False

    def connect(*args):
        nonlocal called
        called = True
        return {"success": True, "data": {}}

    monkeypatch.setattr(web.data_tools, "connect_database", connect)
    response = client("192.0.2.10").post(
        "/api/database/connect",
        json={"md_path": str(tmp_path / "1Cv7.MD"), "user": "", "password": ""},
    )

    assert response.status_code == 403
    assert response.json()["success"] is False
    assert not called


def test_cross_origin_cannot_mutate_database(monkeypatch, tmp_path):
    called = False

    def connect(*args):
        nonlocal called
        called = True
        return {"success": True, "data": {}}

    monkeypatch.setattr(web.data_tools, "connect_database", connect)
    response = client().post(
        "/api/database/connect",
        headers={"Origin": "http://evil.invalid"},
        json={"md_path": str(tmp_path / "1Cv7.MD"), "user": "", "password": ""},
    )

    assert response.status_code == 403
    assert not called


def test_dns_rebinding_host_cannot_mutate_database(monkeypatch, tmp_path):
    called = False

    def connect(*args):
        nonlocal called
        called = True
        return {"success": True, "data": {}}

    monkeypatch.setattr(web.data_tools, "connect_database", connect)
    response = client().post(
        "/api/database/connect",
        headers={"Host": "evil.test", "Origin": "http://evil.test"},
        json={"md_path": str(tmp_path / "1Cv7.MD"), "user": "", "password": ""},
    )

    assert response.status_code == 403
    assert not called


def test_local_connect_status_and_disconnect_contract(monkeypatch, tmp_path):
    md_path = tmp_path / "1Cv7.MD"
    secret = "do-not-return-this"
    received = {}
    disconnected = False

    def connect(path, user, password):
        received.update(path=path, user=user, password=password)
        return {"success": True, "data": {"connected": True, "md_path": path}}

    def disconnect():
        nonlocal disconnected
        disconnected = True
        return {"success": True, "data": {"connected": False, "read_only": True}}

    monkeypatch.setattr(web.data_tools, "connect_database", connect)
    monkeypatch.setattr(web.data_tools, "disconnect_database", disconnect)
    monkeypatch.setattr(
        web.data_tools,
        "get_database_status",
        lambda: {"connected": True, "md_path": str(md_path), "read_only": True},
    )
    monkeypatch.setattr(web.tools, "get_loader", lambda: type("Loader", (), {"is_loaded": False})())

    local = client()
    connected = local.post(
        "/api/database/connect",
        json={"md_path": str(md_path), "user": "reader", "password": secret},
    )
    status = local.get("/api/status")
    closed = local.post("/api/database/disconnect", json={})

    assert connected.status_code == 200
    assert connected.json()["success"] is True
    assert secret not in connected.text
    assert received == {"path": str(md_path), "user": "reader", "password": secret}
    assert status.json() == {
        "loaded": False,
        "database": {"connected": True, "md_path": str(md_path), "read_only": True},
    }
    assert closed.status_code == 200
    assert disconnected
    assert secret not in closed.text


def test_upload_cannot_overwrite_selected_live_metadata(monkeypatch, tmp_path):
    md_path = tmp_path / web.MD_FILENAME
    monkeypatch.setattr(web, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        web.data_tools,
        "get_database_status",
        lambda: {"connected": True, "md_path": str(md_path)},
    )

    response = client().post(
        "/upload",
        files={"file": ("1Cv7.MD", b"replacement", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert not md_path.exists()


def test_upload_parse_error_is_safe_and_bounded(monkeypatch, tmp_path):
    secret = "raw-parser-secret"
    monkeypatch.setattr(web, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(web.data_tools, "get_database_status", lambda: {})
    monkeypatch.setattr(web.tools, "init", lambda path: (_ for _ in ()).throw(ValueError(secret)))

    response = client().post(
        "/upload",
        files={"file": ("1Cv7.MD", b"broken", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "Не удалось разобрать файл 1Cv7.MD."}
    assert secret not in response.text
    assert len(response.text) < 200

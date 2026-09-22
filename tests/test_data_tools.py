"""Atomic metadata/data binding tests."""

from pathlib import Path

import pytest

from mcp_1c77 import data_tools, metadata, tools
from mcp_1c77.data_runtime import DataAccessError


class ExistingRuntime:
    connected = True

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class ExistingLoader:
    is_loaded = True

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def binding_state():
    old_loader = tools._loader
    old_path = tools._md_path
    old_runtime = data_tools._runtime
    old_database = data_tools._database
    yield
    current_loader = tools._loader
    current_runtime = data_tools._runtime
    if current_loader is not old_loader:
        current_loader.close()
    if current_runtime is not None and current_runtime is not old_runtime:
        current_runtime.close()
    tools._loader = old_loader
    tools._md_path = old_path
    data_tools._runtime = old_runtime
    data_tools._database = old_database


def test_failed_tools_init_keeps_old_loader_and_data_binding(monkeypatch, binding_state):
    old_loader = ExistingLoader()
    old_runtime = ExistingRuntime()
    tools._loader = old_loader
    tools._md_path = "old.md"
    data_tools._runtime = old_runtime
    data_tools._database = {"connected": True, "md_path": "old.md"}

    class FailingLoader(ExistingLoader):
        def load(self, path):
            raise ValueError("broken metadata")

    monkeypatch.setattr(tools, "ConfigurationLoader", FailingLoader)

    with pytest.raises(ValueError):
        tools.init("new.md")

    assert tools._loader is old_loader
    assert tools._md_path == "old.md"
    assert data_tools._runtime is old_runtime
    assert data_tools._database["md_path"] == "old.md"
    assert not old_loader.closed
    assert not old_runtime.closed


def test_successful_metadata_reload_disconnects_live_data(monkeypatch, binding_state):
    old_loader = ExistingLoader()
    old_runtime = ExistingRuntime()
    tools._loader = old_loader
    tools._md_path = "old.md"
    data_tools._runtime = old_runtime
    data_tools._database = {"connected": True, "md_path": "old.md"}

    class Loaded(ExistingLoader):
        def load(self, path):
            self.path = path

    monkeypatch.setattr(tools, "ConfigurationLoader", Loaded)
    tools.init("new.md")

    assert isinstance(tools._loader, Loaded)
    assert tools._md_path == "new.md"
    assert old_loader.closed
    assert old_runtime.closed
    assert data_tools._runtime is None
    assert data_tools._database == {}


def test_failed_reconnect_retains_existing_binding(monkeypatch, tmp_path, binding_state):
    md_path = tmp_path / "1Cv7.MD"
    md_path.write_bytes(b"metadata")
    (tmp_path / "1SJOURN.DBF").write_bytes(b"journal")

    old_loader = ExistingLoader()
    old_runtime = ExistingRuntime()
    old_database = {"connected": True, "md_path": "old.md"}
    tools._loader = old_loader
    data_tools._runtime = old_runtime
    data_tools._database = old_database

    class CandidateLoader(ExistingLoader):
        def load(self, path):
            return type("Config", (), {"model_dump": lambda self: {}})()

    class FailingRuntime(ExistingRuntime):
        def connect(self, **arguments):
            raise DataAccessError("ole_error", "safe failure")

    monkeypatch.setattr(data_tools.os, "name", "nt")
    monkeypatch.setattr(metadata, "ConfigurationLoader", CandidateLoader)
    monkeypatch.setattr(data_tools, "DataRuntime", FailingRuntime)

    result = data_tools.connect_database(str(md_path), "user", "secret")

    assert result == {"success": False, "code": "ole_error", "error": "safe failure"}
    assert "secret" not in repr(result)
    assert tools._loader is old_loader
    assert data_tools._runtime is old_runtime
    assert data_tools._database is old_database
    assert not old_runtime.closed


def test_successful_connect_publishes_database_without_credentials(monkeypatch, tmp_path, binding_state):
    md_path = tmp_path / "1Cv7.MD"
    md_path.write_bytes(b"metadata")
    (tmp_path / "1SJOURN.DBF").write_bytes(b"journal")
    tools._loader = ExistingLoader()
    tools._md_path = "old.md"

    class CandidateLoader(ExistingLoader):
        def load(self, path):
            return type("Config", (), {"model_dump": lambda self: {"name": "Demo"}})()

    class ConnectedRuntime(ExistingRuntime):
        def connect(self, **arguments):
            self.arguments = arguments
            return {"version": "7.70"}

    monkeypatch.setattr(data_tools.os, "name", "nt")
    monkeypatch.setattr(metadata, "ConfigurationLoader", CandidateLoader)
    monkeypatch.setattr(data_tools, "DataRuntime", ConnectedRuntime)

    result = data_tools.connect_database(str(md_path), "user", "secret")

    assert result["success"] is True
    assert result["data"]["connected"] is True
    assert result["data"]["read_only"] is True
    assert "secret" not in repr(result)
    assert "user" not in result["data"]


def test_uploaded_md_can_replace_loaded_target_twice(monkeypatch, tmp_path, binding_state):
    target = tmp_path / "1cv7.md"
    target.write_text("old", encoding="utf-8")

    class FileLoader:
        def __init__(self):
            self.is_loaded = False
            self.closed = False

        def load(self, path):
            self.contents = Path(path).read_text(encoding="utf-8")
            self.is_loaded = True

        def close(self):
            self.closed = True
            self.is_loaded = False

    old_loader = FileLoader()
    old_loader.load(target)
    tools._loader = old_loader
    tools._md_path = str(target)
    monkeypatch.setattr(tools, "ConfigurationLoader", FileLoader)
    monkeypatch.setattr(data_tools, "disconnect_database", lambda: None)

    real_replace = tools.os.replace

    def guarded_replace(source, destination):
        if Path(source) == target:
            assert tools._loader.closed
        real_replace(source, destination)

    monkeypatch.setattr(tools.os, "replace", guarded_replace)

    first = tmp_path / "first.md"
    first.write_text("first", encoding="utf-8")
    tools.replace_configuration_file(str(first), str(target))
    first_loader = tools._loader

    second = tmp_path / "second.md"
    second.write_text("second", encoding="utf-8")
    tools.replace_configuration_file(str(second), str(target))

    assert old_loader.closed
    assert first_loader.closed
    assert tools._loader.contents == "second"
    assert target.read_text(encoding="utf-8") == "second"


def test_uploaded_md_failure_restores_file_and_loader(monkeypatch, tmp_path, binding_state):
    target = tmp_path / "1cv7.md"
    target.write_text("old", encoding="utf-8")

    class ValidatingLoader:
        def __init__(self):
            self.is_loaded = False

        def load(self, path):
            self.contents = Path(path).read_text(encoding="utf-8")
            if self.contents == "new-but-rejected":
                raise ValueError("rejected after replacement")
            self.is_loaded = True

        def close(self):
            self.is_loaded = False

    old_loader = ValidatingLoader()
    old_loader.load(target)
    tools._loader = old_loader
    tools._md_path = str(target)
    monkeypatch.setattr(tools, "ConfigurationLoader", ValidatingLoader)
    monkeypatch.setattr(data_tools, "disconnect_database", lambda: None)

    staged = tmp_path / "staged.md"
    staged.write_text("new-but-rejected", encoding="utf-8")

    with pytest.raises(ValueError, match="rejected after replacement"):
        tools.replace_configuration_file(str(staged), str(target))

    assert target.read_text(encoding="utf-8") == "old"
    assert tools._loader.is_loaded
    assert tools._loader.contents == "old"
    assert tools._md_path == str(target)

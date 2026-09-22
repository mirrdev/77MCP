"""Read-only data tools and atomic binding to the selected metadata file."""

from __future__ import annotations

import os
from pathlib import Path
import threading

from .data_runtime import DataAccessError, DataRuntime

database_lock = threading.RLock()
_runtime: DataRuntime | None = None
_database: dict = {}


def _error(exc: DataAccessError) -> dict:
    return {"success": False, "code": exc.code, "error": str(exc)}


def connect_database(md_path: str, user: str, password: str) -> dict:
    """Open OLE first, then publish metadata and data as one selected database."""
    from . import tools
    from .metadata import ConfigurationLoader

    global _runtime, _database
    candidate = None
    loader = ConfigurationLoader()
    try:
        if os.name != "nt":
            raise DataAccessError("unsupported_platform", "Для чтения данных требуется Windows и установленная 1С 7.7.")
        path = Path(md_path)
        if not path.is_absolute() or path.name.lower() != "1cv7.md" or not path.is_file():
            raise DataAccessError("invalid_path", "Укажите абсолютный путь к существующему 1Cv7.MD файловой базы.")
        path = path.resolve()
        if not (path.parent / "1SJOURN.DBF").is_file():
            raise DataAccessError("invalid_database", "Рядом с 1Cv7.MD отсутствует 1SJOURN.DBF файловой базы.")
        config = loader.load(str(path))
        candidate = DataRuntime()
        info = candidate.connect(database_path=str(path.parent), user=user, password=password,
                                 metadata=config.model_dump())
        with database_lock:
            tools.install_loader(loader, str(path))
            loader = None
            _runtime = candidate
            candidate = None
            _database = {**info, "md_path": str(path), "database_path": str(path.parent),
                         "read_only": True, "backend": "ole", "connected": True}
            return {"success": True, "data": dict(_database)}
    except DataAccessError as exc:
        return _error(exc)
    except Exception:
        return _error(DataAccessError("connection_failed", "Не удалось открыть базу. Проверьте файл конфигурации и доступность OLE."))
    finally:
        if candidate is not None:
            candidate.close()
        if loader is not None:
            loader.close()


def disconnect_database() -> dict:
    global _runtime, _database
    with database_lock:
        if _runtime is not None:
            _runtime.close()
        _runtime = None
        _database = {}
    return {"success": True, "data": {"connected": False, "read_only": True}}


def get_database_status() -> dict:
    with database_lock:
        return {**_database, "connected": bool(_runtime and _runtime.connected), "read_only": True}


def _read(operation: str, arguments: dict) -> dict:
    with database_lock:
        try:
            if _runtime is None:
                raise DataAccessError("not_connected", "Подключите базу по локальному пути на http://localhost:8099/.")
            result = _runtime.call(operation, arguments)
            return {"success": True, "data": result, "source": dict(_database)}
        except DataAccessError as exc:
            return _error(exc)


def read_catalog(name: str, fields: list[str] | None = None, filters: dict | None = None,
                 limit: int = 100, offset: int = 0, as_of: str = "") -> dict:
    return _read("read_catalog", locals())


def read_documents(name: str, date_from: str, date_to: str, fields: list[str] | None = None,
                   filters: dict | None = None, limit: int = 100, offset: int = 0) -> dict:
    return _read("read_documents", locals())


def read_document_lines(name: str, reference: str, fields: list[str] | None = None,
                        limit: int = 100, offset: int = 0) -> dict:
    return _read("read_document_lines", locals())


def read_accounts(limit: int = 100, offset: int = 0) -> dict:
    return _read("read_accounts", locals())


def read_accounting_postings(date_from: str, date_to: str, account: str = "",
                             limit: int = 100, offset: int = 0) -> dict:
    return _read("read_accounting_postings", locals())


def read_accounting_totals(date_from: str, date_to: str, accounts: list[str]) -> dict:
    return _read("read_accounting_totals", locals())

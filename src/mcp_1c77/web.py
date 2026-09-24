"""Unified Starlette application: web UI + MCP SSE transport."""

from __future__ import annotations

import os
import ipaddress
import tempfile

from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.concurrency import run_in_threadpool

from . import data_tools, tools
from .api import (
    api_root, api_list_objects, api_get_object, api_get_module, api_get_form,
    api_search, api_validate_path, api_validate_query, api_get_dependencies,
    api_get_dependents, api_export_config, api_export_object,
)
from .server import mcp

DATA_DIR = os.environ.get("MCP_DATA_DIR", "/data")
MD_FILENAME = "1cv7.md"

_HTML_PAGE_PATH = Path(__file__).parent / "static" / "index.html"
_EXPLORER_PAGE_PATH = Path(__file__).parent / "static" / "explorer.html"
HTML_PAGE = _HTML_PAGE_PATH.read_text(encoding="utf-8")



async def upload_page(request: Request) -> HTMLResponse:
    """Serve the upload page."""
    return HTMLResponse(HTML_PAGE)


async def explorer_page(request: Request) -> HTMLResponse:
    """Serve the metadata explorer from the sayfarin fork."""
    return HTMLResponse(_EXPLORER_PAGE_PATH.read_text(encoding="utf-8"))


async def handle_upload(request: Request) -> JSONResponse:
    """Handle file upload or reload of existing file."""
    denied = _mutation_error(request, require_local_peer=False)
    if denied is not None:
        return denied
    os.makedirs(DATA_DIR, exist_ok=True)
    md_path = os.path.join(DATA_DIR, MD_FILENAME)

    database = data_tools.get_database_status()
    selected_md_path = database.get("md_path", "")
    if selected_md_path and Path(selected_md_path).resolve() == Path(md_path).resolve():
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    "Нельзя заменить 1Cv7.MD подключённой базы. "
                    "Сначала отключите базу или выберите другой MCP_DATA_DIR."
                ),
            },
            status_code=409,
        )

    form = await request.form()
    uploaded = form.get("file")
    configuration_replaced = False

    if uploaded is not None and hasattr(uploaded, "read"):
        contents = await uploaded.read()
        if not contents:
            # Empty file in form — try reloading existing
            if not os.path.exists(md_path):
                return JSONResponse({"ok": False, "error": "No file uploaded and no existing file to reload."})
        else:
            temporary_path = ""
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", suffix=".md", dir=DATA_DIR, delete=False
                ) as temporary:
                    temporary.write(contents)
                    temporary_path = temporary.name
                from .metadata import ConfigurationLoader
                candidate = ConfigurationLoader()
                try:
                    await run_in_threadpool(candidate.load, temporary_path)
                finally:
                    candidate.close()
                await run_in_threadpool(
                    tools.replace_configuration_file, temporary_path, md_path
                )
                temporary_path = ""
                configuration_replaced = True
            except Exception:
                if temporary_path:
                    try:
                        os.unlink(temporary_path)
                    except OSError:
                        pass
                return JSONResponse(
                    {"ok": False, "error": "Не удалось разобрать файл 1Cv7.MD."},
                    status_code=400,
                )
    else:
        # No file in request — reload existing
        if not os.path.exists(md_path):
            return JSONResponse({"ok": False, "error": "No file uploaded and no existing file to reload."})

    try:
        if not configuration_replaced:
            await run_in_threadpool(tools.init, md_path)
        config = tools.get_loader().config
        return JSONResponse({
            "ok": True,
            "name": config.name,
            "version": config.version,
        })
    except Exception:
        return JSONResponse(
            {"ok": False, "error": "Не удалось разобрать файл 1Cv7.MD."},
            status_code=400,
        )


def _is_local_request(request: Request) -> bool:
    """Return whether a state-changing request came from this machine."""
    if request.client is None:
        return False
    host = request.client.host.split("%", 1)[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_loopback_host(request: Request) -> bool:
    """Reject DNS-rebinding Host values even for a loopback TCP peer."""
    host = request.url.hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _same_origin(request: Request) -> bool:
    """Allow requests without Origin and same-origin browser requests."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    return origin.rstrip("/").lower() == str(request.base_url).rstrip("/").lower()


def _mutation_error(request: Request, *, require_local_peer: bool = True) -> JSONResponse | None:
    if require_local_peer and not _is_local_request(request):
        return JSONResponse(
            {"success": False, "error": "Изменения разрешены только с этого компьютера."},
            status_code=403,
        )
    if not _is_loopback_host(request):
        return JSONResponse(
            {"success": False, "error": "Запрос отклонён: недопустимое имя локального сервера."},
            status_code=403,
        )
    if not _same_origin(request):
        return JSONResponse(
            {"success": False, "error": "Запрос отклонён: источник страницы не совпадает с сервером."},
            status_code=403,
        )
    return None


async def api_database_connect(request: Request) -> JSONResponse:
    """Connect to a local 1C database without retaining credentials."""
    denied = _mutation_error(request)
    if denied is not None:
        return denied

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Ожидался JSON-запрос."}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse({"success": False, "error": "Ожидался JSON-объект."}, status_code=400)

    md_path = str(body.get("md_path", "")).strip()
    user = str(body.get("user", ""))
    password = str(body.get("password", ""))
    if not md_path:
        return JSONResponse({"success": False, "error": "Укажите путь к файлу 1Cv7.MD."}, status_code=400)
    if not Path(md_path).is_absolute():
        return JSONResponse({"success": False, "error": "Путь к 1Cv7.MD должен быть абсолютным."}, status_code=400)

    result = await run_in_threadpool(data_tools.connect_database, md_path, user, password)
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


async def api_database_disconnect(request: Request) -> JSONResponse:
    """Disconnect the current live database connection."""
    denied = _mutation_error(request)
    if denied is not None:
        return denied
    result = await run_in_threadpool(data_tools.disconnect_database)
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


async def api_reload_metadata(request: Request) -> JSONResponse:
    """Reload metadata through the same local mutation boundary as upload."""
    denied = _mutation_error(request)
    if denied is not None:
        return denied
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected JSON object")
        result = await run_in_threadpool(tools.reload_configuration_checked, str(body.get("path", "")))
    except Exception:
        return JSONResponse({"ok": False, "error": "Не удалось перезагрузить конфигурацию."}, status_code=400)
    return JSONResponse({"ok": True, "message": result})


async def api_status(request: Request) -> JSONResponse:
    """Return current configuration status as JSON."""
    database = data_tools.get_database_status()
    loader = tools.get_loader()
    if not loader.is_loaded:
        return JSONResponse({"loaded": False, "database": database})

    config = loader.config
    coa_count = 1 if config.chart_of_accounts and config.chart_of_accounts.id else 0
    return JSONResponse({
        "loaded": True,
        "name": config.name,
        "version": config.version,
        "file_path": config.file_path,
        "database": database,
        "counts": {
            "constants": len(config.constants),
            "catalogs": len(config.catalogs),
            "documents": len(config.documents),
            "registers": len(config.registers),
            "enums": len(config.enums),
            "reports": len(config.reports),
            "journals": len(config.journals),
            "calc_vars": len(config.calc_vars),
            "chart_of_accounts": coa_count,
        },
    })


async def startup() -> None:
    """Try to load existing configuration on startup."""
    await run_in_threadpool(data_tools.disconnect_database)
    os.makedirs(DATA_DIR, exist_ok=True)
    tools.set_data_dir(DATA_DIR)
    configured_path = os.environ.get("MCP_MD_PATH", "").strip()
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if not candidate.is_absolute():
            print("MCP_MD_PATH must be an absolute path; ignoring it")
            return
        md_path = str(candidate)
    else:
        md_path = os.path.join(DATA_DIR, MD_FILENAME)
    if os.path.exists(md_path):
        try:
            await run_in_threadpool(tools.init, md_path)
            print(f"Auto-loaded configuration from {md_path}")
        except Exception:
            print(f"Failed to auto-load configuration from {md_path}")


# Build both MCP transports. Streamable HTTP must be created before its
# session manager is entered by the application lifespan.
mcp_http_app = mcp.streamable_http_app()
mcp_sse_app = mcp.sse_app()


@asynccontextmanager
async def lifespan(app):
    await startup()
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        await run_in_threadpool(data_tools.disconnect_database)


class Router:
    """Route Streamable HTTP and SSE MCP transports beside the web UI."""

    def __init__(self, http_app, sse_app, lifespan_handler):
        self._http = http_app
        self._sse = sse_app
        self._web = Starlette(
            routes=[
                Route("/", upload_page),
                Route("/explorer", explorer_page),
                Route("/upload", handle_upload, methods=["POST"]),
                Route("/api", api_root),
                Route("/api/status", api_status),
                Route("/api/objects", api_list_objects),
                Route("/api/objects/{type}/{name}", api_get_object),
                Route("/api/objects/{type}/{name}/module", api_get_module),
                Route("/api/objects/{type}/{name}/form", api_get_form),
                Route("/api/objects/{type}/{name}/dependencies", api_get_dependencies),
                Route("/api/objects/{type}/{name}/dependents", api_get_dependents),
                Route("/api/search", api_search),
                Route("/api/validate/path", api_validate_path),
                Route("/api/validate/query", api_validate_query, methods=["POST"]),
                Route("/api/export", api_export_config),
                Route("/api/export/{type}/{name}", api_export_object),
                Route("/api/reload", api_reload_metadata, methods=["POST"]),
                Route("/api/database/connect", api_database_connect, methods=["POST"]),
                Route("/api/database/disconnect", api_database_disconnect, methods=["POST"]),
            ],
            lifespan=lifespan_handler,
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._web(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/mcp":
            await self._http(scope, receive, send)
        elif path.startswith("/sse") or path.startswith("/messages"):
            await self._sse(scope, receive, send)
        else:
            if path.startswith("/api") and not _is_loopback_host(Request(scope, receive)):
                await JSONResponse({"error": "Недопустимое имя локального сервера."}, status_code=403)(scope, receive, send)
                return
            await self._web(scope, receive, send)


app = Router(mcp_http_app, mcp_sse_app, lifespan)

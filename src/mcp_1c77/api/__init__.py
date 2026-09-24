"""REST API для MCP-сервера 1C:Предприятие 7.7.

Предоставляет HTTP endpoints для доступа к метаданным конфигурации.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

# Import from parent package, not relative to avoid circular import
import mcp_1c77.tools as tools

# Маппинг множественных названий типов (из list_objects) в единственные (для get_object и др.)
_TYPE_MAP = {
    "справочники": "справочник",
    "справочник": "справочник",
    "документы": "документ",
    "документ": "документ",
    "регистры": "регистр",
    "регистр": "регистр",
    "перечисления": "перечисление",
    "перечисление": "перечисление",
    "отчёты/обработки": "отчёт",
    "отчеты/обработки": "отчёт",
    "отчёты": "отчёт",
    "отчеты": "отчёт",
    "отчёт": "отчёт",
    "отчет": "отчёт",
    "обработка": "отчёт",
    "обработки": "отчёт",
    "журналы": "журнал",
    "журнал": "журнал",
    "константы": "константа",
    "константа": "константа",
    "виды расчётов": "видрасчёта",
    "виды расчетов": "видрасчёта",
    "видрасчета": "видрасчёта",
    "видрасчёта": "видрасчёта",
    "план счетов": "плансчетов",
    "плансчетов": "плансчетов",
}

_CATEGORY_TO_SINGLE = {
    "справочники": "Справочник",
    "документы": "Документ",
    "регистры": "Регистр",
    "перечисления": "Перечисление",
    "отчёты/обработки": "Отчёт",
    "отчеты/обработки": "Отчёт",
    "журналы": "Журнал",
    "константы": "Константа",
    "виды расчётов": "ВидРасчета",
    "виды расчетов": "ВидРасчета",
    "план счетов": "ПланСчетов",
}


def _normalize_type(object_type: str) -> str:
    """Нормализует название типа из формата list_objects в формат get_object."""
    return _TYPE_MAP.get(object_type.lower(), object_type.lower())


def _json_response(data: Any, status_code: int = 200) -> JSONResponse:
    """Создать JSON response для локального REST API."""
    return JSONResponse(content=data, status_code=status_code)


def _error_response(message: str, status_code: int = 400) -> JSONResponse:
    """Создать JSON response с ошибкой."""
    return _json_response({"ok": False, "error": message}, status_code)


async def api_root(request: Request) -> JSONResponse:
    """Корневой endpoint API - информация о сервере."""
    loader = tools.get_loader()
    return _json_response({
        "name": "1C 7.7 Metadata API",
        "version": "0.4.0",
        "description": "REST API для доступа к метаданным конфигурации 1С 7.7",
        "loaded": loader.is_loaded,
        "endpoints": {
            "status": "/api/status",
            "objects": "/api/objects",
            "object": "/api/objects/{type}/{name}",
            "module": "/api/objects/{type}/{name}/module",
            "form": "/api/objects/{type}/{name}/form",
            "search": "/api/search",
            "validate_path": "/api/validate/path",
            "validate_query": "/api/validate/query",
            "dependencies": "/api/objects/{type}/{name}/dependencies",
            "dependents": "/api/objects/{type}/{name}/dependents",
            "export": "/api/export",
            "export_object": "/api/export/{type}/{name}",
        },
        "tools_count": 26,
    })


async def api_status(request: Request) -> JSONResponse:
    """Статус загруженной конфигурации."""
    loader = tools.get_loader()
    if not loader.is_loaded:
        return _json_response({"loaded": False})
    
    config = loader.config
    coa_count = 1 if config.chart_of_accounts and config.chart_of_accounts.id else 0
    return _json_response({
        "loaded": True,
        "name": config.name,
        "version": config.version,
        "file_path": config.file_path,
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


async def api_list_objects(request: Request) -> JSONResponse:
    """Список объектов метаданных с фильтрацией."""
    object_type = request.query_params.get("type", "")
    try:
        result = tools.list_objects(object_type)
        # Парсим результат из строки в JSON
        # master's tools.list_objects() returns '## Тип (N)' headers and '  - Имя' items
        lines = result.strip().split("\n")
        objects = {}
        current_type = None
        for line in lines:
            stripped = line.strip()
            if line.startswith("## ") or line.startswith("### "):
                # Extract type name, removing count suffix like ' (42)'
                header = stripped.lstrip("# ").strip()
                paren_idx = header.rfind(" (")
                raw_type = header[:paren_idx] if paren_idx > 0 else header
                current_type = _CATEGORY_TO_SINGLE.get(raw_type.lower(), raw_type)
                if current_type not in objects:
                    objects[current_type] = []
            elif stripped.startswith("- ") and current_type:
                # Remove leading '- ' and extract object name (before ' — comment')
                item = stripped[2:].strip()
                # Split on ' — ' to separate name from comment
                name_part = item.split(" — ")[0].strip()
                # Also handle 'Имя: Тип' format for constants
                name_only = name_part.split(":")[0].strip() if ": " in name_part else name_part
                objects[current_type].append(name_only)
        
        return _json_response({"ok": True, "objects": objects, "count": sum(len(v) for v in objects.values())})
    except Exception as e:
        return _error_response(str(e))


async def api_get_object(request: Request) -> JSONResponse:
    """Детальная информация об объекте."""
    object_type = _normalize_type(request.path_params["type"])
    name = request.path_params["name"]
    try:
        result = tools.get_object(object_type, name)
        # Возвращаем как есть или парсим при необходимости
        return _json_response({"ok": True, "data": result})
    except Exception as e:
        return _error_response(str(e))


async def api_get_module(request: Request) -> JSONResponse:
    """Исходный код модуля объекта."""
    object_type = _normalize_type(request.path_params["type"])
    name = request.path_params["name"]
    try:
        result = tools.get_module(object_type, name)
        return _json_response({"ok": True, "module": result})
    except Exception as e:
        return _error_response(str(e))


async def api_get_form(request: Request) -> JSONResponse:
    """Описание формы объекта."""
    object_type = _normalize_type(request.path_params["type"])
    name = request.path_params["name"]
    try:
        result = tools.get_form(object_type, name)
        return _json_response({"ok": True, "form": result})
    except Exception as e:
        return _error_response(str(e))


async def api_search(request: Request) -> JSONResponse:
    """Поиск по метаданным."""
    query = request.query_params.get("q", "")
    if not query:
        return _error_response("Query parameter 'q' is required")
    
    try:
        result = tools.search(query)
        lines = result.strip().split("\n")
        results = []
        for line in lines:
            stripped = line.strip()
            # master's search() returns lines like 'Тип: Имя — Комментарий' (no leading dash)
            # Skip the summary line 'Найдено N результатов:'
            if stripped.startswith("Найдено ") or not stripped:
                continue
            results.append(stripped)
        return _json_response({"ok": True, "query": query, "results": results, "count": len(results)})
    except Exception as e:
        return _error_response(str(e))


async def api_validate_path(request: Request) -> JSONResponse:
    """Валидация пути к реквизиту."""
    object_type = _normalize_type(request.query_params.get("type", ""))
    name = request.query_params.get("name", "")
    path = request.query_params.get("path", "")
    
    if not all([object_type, name, path]):
        return _error_response("Parameters 'type', 'name', 'path' are required")
    
    try:
        result = tools.validate_field_path(object_type, name, path)
        valid = "не найден" not in result.lower() and "ошибка" not in result.lower()
        return _json_response({"ok": True, "valid": valid, "message": result})
    except Exception as e:
        return _error_response(str(e))


async def api_validate_query(request: Request) -> JSONResponse:
    """Валидация запроса 1С."""
    body = await request.json() if request.method == "POST" else {}
    query_text = body.get("query") or request.query_params.get("query", "")
    
    if not query_text:
        return _error_response("Query text is required")
    
    try:
        result = tools.validate_query(query_text)
        valid = "ошибка" not in result.lower()
        return _json_response({"ok": True, "valid": valid, "message": result})
    except Exception as e:
        return _error_response(str(e))


async def api_get_dependencies(request: Request) -> JSONResponse:
    """Зависимости объекта (что использует данный объект)."""
    object_type = _normalize_type(request.path_params["type"])
    name = request.path_params["name"]
    try:
        result = tools.get_object_dependencies(object_type, name)
        # Парсим результат
        lines = result.strip().split("\n")
        dependencies = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- "):
                dependencies.append(stripped[2:].strip())
        return _json_response({
            "ok": True, 
            "object": {"type": object_type, "name": name},
            "dependencies": dependencies,
            "count": len(dependencies)
        })
    except Exception as e:
        return _error_response(str(e))


async def api_get_dependents(request: Request) -> JSONResponse:
    """Зависимые объекты (кто использует данный объект)."""
    object_type = _normalize_type(request.path_params["type"])
    name = request.path_params["name"]
    try:
        result = tools.find_dependent_objects(object_type, name)
        lines = result.strip().split("\n")
        dependents = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- "):
                dependents.append(stripped[2:].strip())
        return _json_response({
            "ok": True,
            "object": {"type": object_type, "name": name},
            "dependents": dependents,
            "count": len(dependents)
        })
    except Exception as e:
        return _error_response(str(e))


async def api_export_config(request: Request) -> JSONResponse:
    """Экспорт всей конфигурации в JSON."""
    if request.query_params.get("save", "false").lower() == "true":
        return _error_response("Сохраняйте JSON на стороне клиента.")
    try:
        data = json.loads(tools.export_to_json())
        return _json_response({"ok": True, "data": data})
    except Exception as e:
        return _error_response(str(e))


async def api_export_object(request: Request) -> JSONResponse:
    """Экспорт объекта в JSON."""
    object_type = _normalize_type(request.path_params["type"])
    name = request.path_params["name"]
    try:
        result = tools.export_object_to_json(object_type, name)
        data = json.loads(result)
        return _json_response({"ok": True, "data": data})
    except Exception as e:
        return _error_response(str(e))


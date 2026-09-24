#!/usr/bin/env python3
"""CLI утилита для работы с MCP-сервером 1C:Предприятие 7.7.

Командная строка для доступа к метаданным конфигурации.
"""

import argparse
import json
import os
import sys
from typing import Optional

from .client import MetadataClient, ConfigError


def cmd_status(client: MetadataClient, args: argparse.Namespace) -> int:
    """Показать статус сервера."""
    status = client.get_status()
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        if status.get('loaded'):
            print(f"[OK] Конфигурация загружена")
            print(f"   Название: {status.get('name', 'N/A')}")
            print(f"   Версия: {status.get('version', 'N/A')}")
            counts = status.get('counts', {})
            print(f"\n   Объекты:")
            for key, value in counts.items():
                print(f"     - {key}: {value}")
        else:
            print("[FAIL] Конфигурация не загружена")
    return 0


def cmd_search(client: MetadataClient, args: argparse.Namespace) -> int:
    """Поиск по метаданным."""
    results = client.search(args.query)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if results:
            print(f"Найдено {len(results)} результатов:")
            for item in results[:args.limit]:
                print(f"  - {item}")
            if len(results) > args.limit:
                print(f"  ... и ещё {len(results) - args.limit}")
        else:
            print("Ничего не найдено")
    return 0


def cmd_list(client: MetadataClient, args: argparse.Namespace) -> int:
    """Список объектов."""
    result = client.list_objects(args.type)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        objects = result.get('objects', {})
        total = result.get('count', 0)
        print(f"Всего объектов: {total}")
        for obj_type, names in objects.items():
            print(f"\n{obj_type} ({len(names)}):")
            for name in names[:args.limit]:
                print(f"  - {name}")
            if len(names) > args.limit:
                print(f"  ... и ещё {len(names) - args.limit}")
    return 0


def cmd_object(client: MetadataClient, args: argparse.Namespace) -> int:
    """Информация об объекте."""
    data = client.get_object(args.type, args.name)
    if args.json:
        print(json.dumps({"data": data}, indent=2, ensure_ascii=False))
    else:
        print(data)
    return 0


def cmd_module(client: MetadataClient, args: argparse.Namespace) -> int:
    """Модуль объекта."""
    module = client.get_module(args.type, args.name)
    if module:
        print(module)
    else:
        print("Модуль отсутствует", file=sys.stderr)
        return 1
    return 0


def cmd_form(client: MetadataClient, args: argparse.Namespace) -> int:
    """Форма объекта."""
    form = client.get_form(args.type, args.name)
    if form:
        print(form)
    else:
        print("Форма отсутствует", file=sys.stderr)
        return 1
    return 0


def cmd_deps(client: MetadataClient, args: argparse.Namespace) -> int:
    """Зависимости объекта."""
    deps = client.get_dependencies(args.type, args.name)
    if args.json:
        print(json.dumps(deps, indent=2, ensure_ascii=False))
    else:
        if deps:
            print(f"Использует объектов: {len(deps)}")
            for dep in deps:
                print(f"  - {dep}")
        else:
            print("Зависимости не найдены")
    return 0


def cmd_dependents(client: MetadataClient, args: argparse.Namespace) -> int:
    """Зависимые объекты."""
    dependents = client.get_dependents(args.type, args.name)
    if args.json:
        print(json.dumps(dependents, indent=2, ensure_ascii=False))
    else:
        if dependents:
            print(f"Используют этот объект: {len(dependents)}")
            for dep in dependents:
                print(f"  - {dep}")
        else:
            print("Зависимые объекты не найдены")
    return 0


def cmd_validate_path(client: MetadataClient, args: argparse.Namespace) -> int:
    """Валидация пути."""
    result = client.validate_field_path(args.type, args.name, args.path)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        status = "[OK] Валиден" if result.get('valid') else "[FAIL] Не валиден"
        print(f"{status}: {result.get('message', '')}")
    return 0 if result.get('valid') else 1


def cmd_validate_query(client: MetadataClient, args: argparse.Namespace) -> int:
    """Валидация запроса."""
    query_text = args.query
    if not query_text and not sys.stdin.isatty():
        query_text = sys.stdin.read()
    
    if not query_text:
        print("Ошибка: требуется текст запроса", file=sys.stderr)
        return 1
    
    result = client.validate_query(query_text)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        status = "[OK] Валиден" if result.get('valid') else "[FAIL] Не валиден"
        print(f"{status}: {result.get('message', '')}")
    return 0 if result.get('valid') else 1


def cmd_export(client: MetadataClient, args: argparse.Namespace) -> int:
    """Экспорт конфигурации."""
    if args.object_type and args.name:
        data = client.export_object(args.object_type, args.name)
    else:
        data = client.export_config()

    if args.save:
        if not args.output:
            print("Укажите --output для локального JSON-файла", file=sys.stderr)
            return 1
        from pathlib import Path
        Path(args.output).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Сохранено в {args.output}")
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def cmd_info(client: MetadataClient, args: argparse.Namespace) -> int:
    """Информация о сервере API."""
    info = client.get_server_info()
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"[API] {info.get('name', 'API Server')}")
        print(f"   Версия: {info.get('version', 'N/A')}")
        print(f"   Описание: {info.get('description', 'N/A')}")
        print(f"\n   Доступные endpoints:")
        for name, path in info.get('endpoints', {}).items():
            print(f"     {name}: {path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Основная функция CLI."""
    default_url = os.environ.get('MCP_SERVER_URL', 'http://localhost:8099')

    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument('--url', default=default_url,
                               help=f'URL сервера (по умолчанию: {default_url})')
    parent_parser.add_argument('--json', action='store_true',
                               help='Вывод в формате JSON')

    parser = argparse.ArgumentParser(
        prog='mcp-1c77',
        description='CLI для работы с метаданными 1С 7.7',
        parents=[parent_parser]
    )

    subparsers = parser.add_subparsers(dest='command', help='Команды')

    # status
    p_status = subparsers.add_parser('status', help='Статус сервера', parents=[parent_parser])
    p_status.set_defaults(func=cmd_status)

    # search
    p_search = subparsers.add_parser('search', help='Поиск по метаданным', parents=[parent_parser])
    p_search.add_argument('query', help='Поисковый запрос')
    p_search.add_argument('--limit', type=int, default=20, help='Макс. результатов')
    p_search.set_defaults(func=cmd_search)

    # list
    p_list = subparsers.add_parser('list', help='Список объектов', parents=[parent_parser])
    p_list.add_argument('--type', '-t', default='', help='Тип объекта')
    p_list.add_argument('--limit', type=int, default=50, help='Макс. результатов')
    p_list.set_defaults(func=cmd_list)

    # object
    p_object = subparsers.add_parser('object', help='Информация об объекте', parents=[parent_parser])
    p_object.add_argument('type', help='Тип объекта')
    p_object.add_argument('name', help='Имя объекта')
    p_object.set_defaults(func=cmd_object)

    # module
    p_module = subparsers.add_parser('module', help='Модуль объекта', parents=[parent_parser])
    p_module.add_argument('type', help='Тип объекта')
    p_module.add_argument('name', help='Имя объекта')
    p_module.set_defaults(func=cmd_module)

    # form
    p_form = subparsers.add_parser('form', help='Форма объекта', parents=[parent_parser])
    p_form.add_argument('type', help='Тип объекта')
    p_form.add_argument('name', help='Имя объекта')
    p_form.set_defaults(func=cmd_form)

    # deps
    p_deps = subparsers.add_parser('deps', help='Зависимости объекта', parents=[parent_parser])
    p_deps.add_argument('type', help='Тип объекта')
    p_deps.add_argument('name', help='Имя объекта')
    p_deps.set_defaults(func=cmd_deps)

    # dependents
    p_dependents = subparsers.add_parser('dependents', help='Зависимые объекты', parents=[parent_parser])
    p_dependents.add_argument('type', help='Тип объекта')
    p_dependents.add_argument('name', help='Имя объекта')
    p_dependents.set_defaults(func=cmd_dependents)

    # validate-path
    p_vpath = subparsers.add_parser('validate-path', help='Валидация пути', parents=[parent_parser])
    p_vpath.add_argument('type', help='Тип объекта')
    p_vpath.add_argument('name', help='Имя объекта')
    p_vpath.add_argument('path', help='Путь к реквизиту')
    p_vpath.set_defaults(func=cmd_validate_path)

    # validate-query
    p_vquery = subparsers.add_parser('validate-query', help='Валидация запроса', parents=[parent_parser])
    p_vquery.add_argument('query', nargs='?', help='Текст запроса')
    p_vquery.set_defaults(func=cmd_validate_query)

    # export
    p_export = subparsers.add_parser('export', help='Экспорт в JSON', parents=[parent_parser])
    p_export.add_argument('--type', '-t', help='Тип объекта')
    p_export.add_argument('--name', '-n', help='Имя объекта')
    p_export.add_argument('--save', '-s', action='store_true', help='Сохранить в файл')
    p_export.add_argument('--output', '-o', help='Путь файла')
    p_export.set_defaults(func=cmd_export)

    # info
    p_info = subparsers.add_parser('info', help='Информация о сервере', parents=[parent_parser])
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    client = MetadataClient(args.url)

    try:
        return args.func(client, args)
    except ConfigError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        print(f"Убедитесь, что сервер запущен на {args.url} (запуск: python -m mcp_1c77)", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())

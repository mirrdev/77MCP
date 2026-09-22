"""MCP server for 1C:Enterprise 7.7 configuration metadata.

Provides LLM clients with access to metadata objects, attributes, modules,
and forms from 1Cv7.MD configuration files.
"""

from mcp.server.fastmcp import FastMCP

from . import tools, data_tools

mcp = FastMCP("1c77-metadata")


@mcp.tool()
def reload_configuration(path: str = "") -> str:
    """Перезагрузить конфигурацию (или загрузить другой файл).

    Args:
        path: Путь к файлу 1Cv7.MD. Если пустой — перезагружает текущий файл.
    """
    return tools.reload_configuration(path)


@mcp.tool()
def list_objects(object_type: str = "") -> str:
    """Список объектов метаданных конфигурации.

    Args:
        object_type: Тип объекта для фильтрации (Справочник, Документ, Регистр,
                     Перечисление, Отчёт, Журнал, Константа, ВидРасчёта).
                     Пустая строка — показать все типы.
    """
    return tools.list_objects(object_type)


@mcp.tool()
def get_object(object_type: str, name: str) -> str:
    """Детальная информация об объекте метаданных (реквизиты, табличные части).

    Args:
        object_type: Тип объекта (Справочник, Документ, Регистр, Перечисление, и т.д.)
        name: Имя объекта.
    """
    return tools.get_object(object_type, name)


@mcp.tool()
def get_module(object_type: str, name: str, start_line: int = 0, end_line: int = 0) -> str:
    """Получить исходный код модуля объекта метаданных.

    Args:
        object_type: Тип объекта (Справочник, Документ, Отчёт, ВидРасчёта).
        name: Имя объекта.
        start_line: Начальная строка (1-индексация). 0 = с начала.
        end_line: Конечная строка включительно. 0 = до конца.
                  При обоих 0 модуль усекается до ~1500 строк, если он большой.
    """
    return tools.get_module(object_type, name, start_line, end_line)


@mcp.tool()
def get_form(object_type: str, name: str) -> str:
    """Получить описание формы объекта (элементы управления).

    Args:
        object_type: Тип объекта (Справочник, Документ, Отчёт, ВидРасчёта).
        name: Имя объекта.
    """
    return tools.get_form(object_type, name)


@mcp.tool()
def search(query: str) -> str:
    """Поиск по объектам метаданных (по имени, синониму, комментарию).

    Args:
        query: Строка поиска.
    """
    return tools.search(query)


@mcp.tool()
def get_configuration_info() -> str:
    """Общая информация о загруженной конфигурации."""
    return tools.get_configuration_info()


@mcp.tool()
def validate_field_path(object_type: str, name: str, path: str) -> str:
    """Проверить валидность пути обращения к реквизиту объекта.

    Args:
        object_type: Тип (Документ, Справочник, Регистр, Перечисление)
        name: Имя объекта
        path: Путь к реквизиту (напр. "Сумма", "Товар.Артикул", "Партия.ГТД.Наименование")
    """
    return tools.validate_field_path(object_type, name, path)


@mcp.tool()
def validate_query(query_text: str) -> str:
    """Проверить все пути обращений к реквизитам в тексте запроса/кода 1С 7.7.

    Args:
        query_text: Полный текст запроса или фрагмент кода
    """
    return tools.validate_query(query_text)


@mcp.tool()
def search_field(field_name: str, object_type: str = "") -> str:
    """Найти все объекты, содержащие реквизит с данным именем (обратный поиск).

    Args:
        field_name: Имя реквизита для поиска
        object_type: Опционально: Документ, Справочник, Регистр
    """
    return tools.search_field(field_name, object_type)


@mcp.tool()
def get_objects_batch(object_type: str, names: list[str]) -> str:
    """Пакетное получение метаданных нескольких объектов за один вызов.

    Args:
        object_type: Тип объектов (Документ, Справочник, и т.д.)
        names: Список имён объектов
    """
    return tools.get_objects_batch(object_type, names)


@mcp.tool()
def get_global_module(start_line: int = 0, end_line: int = 0) -> str:
    """Получить исходный код глобального модуля конфигурации.

    Глобальный модуль — это модуль, доступный из любого места конфигурации 1С 7.7.
    Хранится в контейнере TypedText (стрим ModuleText_Number1).

    Args:
        start_line: Начальная строка (1-индексация). 0 = с начала.
        end_line: Конечная строка включительно. 0 = до конца.
                  При обоих 0 модуль усекается до ~1500 строк, если он большой.
    """
    return tools.get_global_module(start_line, end_line)


@mcp.tool()
def list_modules() -> str:
    """Список всех модулей конфигурации, включая глобальный модуль.

    Показывает какие объекты имеют модули с исходным кодом.
    """
    return tools.list_modules()


@mcp.tool()
def search_in_modules(query: str, context_lines: int = 0, limit: int = 200) -> str:
    """Полнотекстовый поиск по исходному коду всех модулей конфигурации.

    Args:
        query: Строка для поиска (без учёта регистра).
        context_lines: Сколько строк до и после совпадения показывать.
        limit: Максимум совпадений в ответе (по всем модулям).
    """
    return tools.search_in_modules(query, context_lines, limit)


@mcp.tool()
def resolve_id(object_id: str) -> str:
    """Определить тип и имя объекта метаданных по его внутреннему ID.

    Args:
        object_id: Внутренний идентификатор объекта (числовая строка)
    """
    return tools.resolve_id(object_id)


@mcp.tool()
def get_database_info() -> dict:
    """Состояние подключения к реальной файловой базе 7.7 и путь источника данных.

    Подключение выполняется пользователем на http://localhost:8099/ по локальному
    пути к 1Cv7.MD. Загрузка копии MD предоставляет только метаданные.
    """
    return data_tools.get_database_status()


@mcp.tool()
def read_catalog(name: str, fields: list[str] | None = None, filters: dict | None = None,
                 limit: int = 100, offset: int = 0, as_of: str = "") -> dict:
    """Читать элементы справочника с реквизитами и ссылками, только чтение.

    name — имя из list_objects; fields — имена реквизитов. filters — равенство
    полей скалярным значениям. as_of — дата YYYY-MM-DD периодических реквизитов.
    limit 1..500; offset 0..100000; has_more/next_offset задают продолжение.
    Денежные/числовые значения представлены десятичными строками без округления.
    """
    return data_tools.read_catalog(name, fields, filters, limit, offset, as_of)


@mcp.tool()
def read_documents(name: str, date_from: str, date_to: str, fields: list[str] | None = None,
                   filters: dict | None = None, limit: int = 100, offset: int = 0) -> dict:
    """Читать шапки документов за включительный период YYYY-MM-DD.

    Возвращает ссылки для read_document_lines. fields/filters используют имена
    реквизитов из get_object. limit 1..500, offset 0..100000. Ничего не проводит.
    """
    return data_tools.read_documents(name, date_from, date_to, fields, filters, limit, offset)


@mcp.tool()
def read_document_lines(name: str, reference: str, fields: list[str] | None = None,
                        limit: int = 100, offset: int = 0) -> dict:
    """Читать табличную часть документа по reference из read_documents.

    name — вид документа; fields — реквизиты табличной части; limit 1..500.
    """
    return data_tools.read_document_lines(name, reference, fields, limit, offset)


@mcp.tool()
def read_accounts(limit: int = 100, offset: int = 0) -> dict:
    """Читать реальные счета плана счетов базы 7.7. limit 1..500, offset 0..100000."""
    return data_tools.read_accounts(limit, offset)


@mcp.tool()
def read_accounting_postings(date_from: str, date_to: str, account: str = "",
                             limit: int = 100, offset: int = 0) -> dict:
    """Читать проводки бухгалтерских операций: дебет, кредит, сумма и аналитика.

    Период YYYY-MM-DD включительно; account — необязательный точный код счёта
    дебета или кредита. limit 1..500. Суммы — десятичные строки.
    """
    return data_tools.read_accounting_postings(date_from, date_to, account, limit, offset)


@mcp.tool()
def read_accounting_totals(date_from: str, date_to: str, accounts: list[str]) -> dict:
    """Штатные итоги 7.7 по кодам счетов: СНД/СНК, ДО/КО, СКД/СКК.

    Период YYYY-MM-DD включительно, accounts — непустой список кодов счетов.
    Используйте для сверки с 8.3 по одинаковому периоду и уровню счетов.
    """
    return data_tools.read_accounting_totals(date_from, date_to, accounts)

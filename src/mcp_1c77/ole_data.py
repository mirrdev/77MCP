"""Finite, read-only access to 1C 7.7 data through OLE Automation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import re

from .data_runtime import DataAccessError


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_NAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*\Z")


class OleReader:
    """Own one V77.Application instance and expose only fixed read operations."""

    def __init__(self, database_path: str, user: str, password: str, metadata: dict):
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise DataAccessError("ole_unavailable", "В окружении отсутствует поддержка OLE (pywin32).") from exc

        self._pythoncom = pythoncom
        self._pythoncom.CoInitialize()
        self._app = None
        self._metadata = metadata
        self._catalogs = {item["name"]: item for item in metadata.get("catalogs", [])}
        self._documents = {item["name"]: item for item in metadata.get("documents", [])}
        self._document_references: dict[str, tuple[str, object]] = {}
        try:
            if any('"' in item or any(ord(c) < 32 for c in item)
                   for item in (database_path, user, password)):
                raise DataAccessError("invalid_credentials", "Путь, имя и пароль не должны содержать кавычки или управляющие символы.")
            self._app = win32com.client.DispatchEx("V77.Application")
            command = f'/D"{database_path}"'
            if user:
                command += f' /N"{user}"'
            if password:
                command += f' /P"{password}"'
            if not self._app.Initialize(self._app.RMTrade, command, "NO_SPLASH_SHOW"):
                raise DataAccessError("connection_failed", "1С 7.7 отказала в подключении к информационной базе.")
        except DataAccessError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise DataAccessError("ole_unavailable", "Не удалось создать или инициализировать V77.Application.") from exc

    def info(self) -> dict:
        return {"configuration": self._metadata.get("name", ""), "version": self._metadata.get("version", "")}

    def close(self) -> None:
        app, self._app = self._app, None
        if app is not None:
            try:
                self._pythoncom.CoDisconnectObject(app)
            except Exception:
                pass
        if hasattr(self, "_pythoncom"):
            try:
                self._pythoncom.CoUninitialize()
            except Exception:
                pass

    def call(self, operation: str, arguments: dict) -> dict:
        methods = {
            "read_catalog": self.read_catalog,
            "read_documents": self.read_documents,
            "read_document_lines": self.read_document_lines,
            "read_accounts": self.read_accounts,
            "read_accounting_postings": self.read_accounting_postings,
            "read_accounting_totals": self.read_accounting_totals,
        }
        method = methods.get(operation)
        if method is None:
            raise DataAccessError("unsupported_operation", "Операция чтения не поддерживается.")
        return method(**arguments)

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise DataAccessError("invalid_limit", "limit должен быть целым числом от 1 до 500.")
        if type(offset) is not int or not 0 <= offset <= 100_000:
            raise DataAccessError("invalid_offset", "offset должен быть целым числом от 0 до 100000.")
        return limit, offset

    @staticmethod
    def _date(value: str, field: str) -> datetime:
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            raise DataAccessError("invalid_date", f"{field} должна иметь формат YYYY-MM-DD.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise DataAccessError("invalid_date", f"{field} содержит недопустимую дату.") from exc
        # pywin32 treats naive/local midnight as local time and 1C 7.7 receives
        # the previous calendar date. UTC matches a native 1C Date value.
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)

    @staticmethod
    def _name(value: str, kind: str) -> str:
        if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
            raise DataAccessError("invalid_name", f"Недопустимое имя {kind}.")
        return value

    @staticmethod
    def _fields(requested, allowed: dict[str, str], defaults: list[str]) -> list[str]:
        fields = defaults if requested is None else requested
        if not isinstance(fields, list) or not fields or any(not isinstance(x, str) for x in fields):
            raise DataAccessError("invalid_fields", "fields должен быть непустым списком имён полей.")
        unknown = [x for x in fields if x not in allowed]
        if unknown:
            raise DataAccessError("unknown_field", f"Неизвестное поле: {unknown[0]}.")
        return fields

    @staticmethod
    def _filters(filters, allowed: dict[str, str]) -> dict:
        if filters is None:
            return {}
        if not isinstance(filters, dict):
            raise DataAccessError("invalid_filters", "filters должен быть объектом.")
        for key, value in filters.items():
            if key not in allowed:
                raise DataAccessError("unknown_field", f"Неизвестное поле фильтра: {key}.")
            if value is not None and type(value) not in (str, int, float, bool):
                raise DataAccessError("invalid_filter", "Поддерживаются только скалярные фильтры равенства.")
        return filters

    def _create(self, type_name: str):
        return self._app.CreateObject(type_name)

    @staticmethod
    def _call(obj, russian: str, english: str, *arguments):
        """Call a 7.7 method by its runtime or language alias."""
        ole_object = getattr(obj, "_oleobj_", None)
        if ole_object is not None:
            for name in (russian, english):
                try:
                    dispid = ole_object.GetIDsOfNames(name)
                except Exception:
                    continue
                return ole_object.Invoke(dispid, 0, 1, True, *arguments)
            raise DataAccessError("ole_api_mismatch", f"OLE 1С 7.7 не предоставляет метод {russian}.")
        for name in (russian, english):
            try:
                member = getattr(obj, name)
            except (AttributeError, TypeError):
                continue
            if callable(member):
                return member(*arguments)
        raise DataAccessError("ole_api_mismatch", f"OLE 1С 7.7 не предоставляет метод {russian}.")

    def _serialize(self, value, type_code: str = ""):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (datetime, date)) or value.__class__.__module__ == "pywintypes":
            try:
                return value.strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                pass
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, (int, float)) and type_code == "Boolean":
            return bool(value)
        if isinstance(value, (int, float)):
            return format(Decimal(str(value)), "f") if type_code in ("N", "Число") else value
        if isinstance(value, str):
            return value
        try:
            reference = str(self._app.ValueToStringInternal(value))
            try:
                presentation = str(value)
            except Exception:
                presentation = ""
            result = {
                "reference": reference,
                "presentation": presentation,
                "type": {
                    "B": "Справочник", "Справочник": "Справочник",
                    "O": "Документ", "Документ": "Документ",
                    "P": "Счет", "ПланСчетов": "Счет", "Счет": "Счет",
                }.get(type_code, type_code or "АгрегатныйОбъект"),
            }
            try:
                code = value.Code
                if code is not None:
                    result["code"] = str(code).strip()
            except Exception:
                pass
            return result
        except Exception as exc:
            raise DataAccessError("unsupported_value", "OLE вернула неподдерживаемое значение поля.") from exc

    def _value(self, obj, field: str, type_code: str = ""):
        try:
            method_aliases = {
                "ТекущийЭлемент": "CurrentItem",
                "ЭтоГруппа": "IsGroup",
                "ПометкаУдаления": "DeleteMark",
                "ТекущийДокумент": "CurrentDocument",
                "Проведен": "IsTransacted",
            }
            if field in method_aliases:
                value = self._call(obj, field, method_aliases[field])
            else:
                value = getattr(obj, field)
            if callable(value) and not hasattr(value, "_oleobj_"):
                value = value()
            return self._serialize(value, type_code)
        except DataAccessError:
            raise
        except Exception as exc:
            raise DataAccessError("field_read_failed", f"Не удалось прочитать поле {field}.") from exc

    @staticmethod
    def _matches(row: dict, filters: dict) -> bool:
        for key, expected in filters.items():
            actual = row[key]
            if isinstance(actual, dict):
                actual = actual.get("reference") if isinstance(expected, str) else actual
            elif isinstance(actual, str) and type(expected) in (int, float):
                try:
                    if Decimal(actual) == Decimal(str(expected)):
                        continue
                except ArithmeticError:
                    pass
            if actual != expected:
                return False
        return True

    @staticmethod
    def _result(rows: list, limit: int, offset: int) -> dict:
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"rows": rows, "has_more": has_more,
                "next_offset": offset + limit if has_more else None,
                "offset": offset, "limit": limit}

    def read_catalog(self, name, fields=None, filters=None, limit=100, offset=0, as_of="") -> dict:
        limit, offset = self._page(limit, offset)
        meta = self._catalogs.get(self._name(name, "справочника"))
        if meta is None:
            raise DataAccessError("unknown_catalog", "Справочник отсутствует в выбранной конфигурации.")
        allowed = {"reference": "ТекущийЭлемент", "code": "Код", "name": "Наименование", "is_group": "ЭтоГруппа",
                   "deleted": "ПометкаУдаления", "parent": "Родитель", "owner": "Владелец"}
        types = {"reference": "B", "code": "S", "name": "S",
                 "is_group": "Boolean", "deleted": "Boolean"}
        for attr in meta.get("attributes", []):
            allowed[attr["name"]] = attr["name"]
            types[attr["name"]] = attr.get("type", "")
        selected = self._fields(fields, allowed, ["reference", "code", "name", "is_group", "deleted"])
        filters = self._filters(filters, allowed)
        obj = self._create(f"Справочник.{name}")
        if as_of:
            self._call(obj, "ИспользоватьДату", "UseDate", self._date(as_of, "as_of"))
        self._call(obj, "ВыбратьЭлементы", "SelectItems")
        rows, matched = [], 0
        while self._call(obj, "ПолучитьЭлемент", "GetItem") == 1 and len(rows) <= limit:
            presentation_keys = ["name", "code"] if "reference" in selected else []
            keys = list(dict.fromkeys(selected + list(filters) + presentation_keys))
            row = {key: self._value(obj, allowed[key], types.get(key, "")) for key in keys}
            if isinstance(row.get("reference"), dict):
                row["reference"]["presentation"] = row.get("name") or row.get("code") or ""
            if self._matches(row, filters):
                if matched >= offset:
                    rows.append({key: row[key] for key in selected})
                matched += 1
        return self._result(rows, limit, offset)

    def read_documents(self, name, date_from, date_to, fields=None, filters=None,
                       limit=100, offset=0) -> dict:
        limit, offset = self._page(limit, offset)
        start, end = self._date(date_from, "date_from"), self._date(date_to, "date_to")
        if start > end:
            raise DataAccessError("invalid_period", "date_from не может быть позже date_to.")
        meta = self._documents.get(self._name(name, "документа"))
        if meta is None:
            raise DataAccessError("unknown_document", "Документ отсутствует в выбранной конфигурации.")
        allowed = {"reference": "ТекущийДокумент", "number": "НомерДок", "date": "ДатаДок",
                   "posted": "Проведен", "deleted": "ПометкаУдаления"}
        types = {"reference": "O", "number": "S", "date": "D", "posted": "Boolean", "deleted": "Boolean"}
        for attr in meta.get("head_attributes", []):
            allowed[attr["name"]] = attr["name"]
            types[attr["name"]] = attr.get("type", "")
        selected = self._fields(fields, allowed, ["reference", "number", "date", "posted", "deleted"])
        filters = self._filters(filters, allowed)
        obj = self._create(f"Документ.{name}")
        self._call(obj, "ВыбратьДокументы", "SelectDocuments", start, end)
        rows, matched = [], 0
        while self._call(obj, "ПолучитьДокумент", "GetDocument") == 1 and len(rows) <= limit:
            presentation_keys = ["number", "date"] if "reference" in selected else []
            keys = list(dict.fromkeys(selected + list(filters) + presentation_keys))
            row = {key: self._value(obj, allowed[key], types.get(key, "")) for key in keys}
            if isinstance(row.get("reference"), dict):
                row["reference"]["presentation"] = " ".join(
                    str(value) for value in (row.get("number"), row.get("date")) if value)
            document_reference = row.get("reference")
            if isinstance(document_reference, dict):
                current = self._call(obj, "ТекущийДокумент", "CurrentDocument")
                self._document_references[document_reference["reference"]] = (name, current)
            if self._matches(row, filters):
                if matched >= offset:
                    rows.append({key: row[key] for key in selected})
                matched += 1
        return self._result(rows, limit, offset)

    def _document_reference(self, name: str, reference: str):
        cached = self._document_references.get(reference) if isinstance(reference, str) else None
        if cached is None or cached[0] != name:
            raise DataAccessError("invalid_reference", "Используйте ссылку из read_documents текущего подключения.")
        return cached[1]

    def read_document_lines(self, name, reference, fields=None, limit=100, offset=0) -> dict:
        limit, offset = self._page(limit, offset)
        meta = self._documents.get(self._name(name, "документа"))
        if meta is None:
            raise DataAccessError("unknown_document", "Документ отсутствует в выбранной конфигурации.")
        allowed, types = {"line_number": "НомерСтроки"}, {"line_number": ""}
        for attr in meta.get("table_attributes", []):
            allowed[attr["name"]] = attr["name"]
            types[attr["name"]] = attr.get("type", "")
        selected = self._fields(fields, allowed, list(allowed))
        obj = self._create(f"Документ.{name}")
        value = self._document_reference(name, reference)
        if self._call(obj, "НайтиДокумент", "FindDocument", value) != 1:
            raise DataAccessError("document_not_found", "Документ не найден или имеет другой вид.")
        self._call(obj, "ВыбратьСтроки", "SelectLines")
        rows, index = [], 0
        while self._call(obj, "ПолучитьСтроку", "GetLine") == 1 and len(rows) <= limit:
            if index >= offset:
                rows.append({key: self._value(obj, allowed[key], types.get(key, "")) for key in selected})
            index += 1
        result = self._result(rows, limit, offset)
        result["reference"] = reference
        return result

    def read_accounts(self, limit=100, offset=0) -> dict:
        limit, offset = self._page(limit, offset)
        obj = self._create("Счет")
        self._call(obj, "ВыбратьСчета", "SelectAccounts")
        rows, index = [], 0
        while self._call(obj, "ПолучитьСчет", "GetAccount") == 1 and len(rows) <= limit:
            if index >= offset:
                rows.append({"code": self._value(obj, "Код", "S"),
                             "name": self._value(obj, "Наименование", "S"),
                             "is_group": self._value(obj, "ЭтоГруппа", "Boolean")})
            index += 1
        return self._result(rows, limit, offset)

    def read_accounting_postings(self, date_from, date_to, account="", limit=100, offset=0) -> dict:
        limit, offset = self._page(limit, offset)
        start, end = self._date(date_from, "date_from"), self._date(date_to, "date_to")
        if start > end:
            raise DataAccessError("invalid_period", "date_from не может быть позже date_to.")
        if not isinstance(account, str):
            raise DataAccessError("invalid_account", "account должен быть строкой.")
        operation = self._create("Операция")
        self._call(operation, "ВыбратьОперации", "SelectOpers", start, end)
        rows, matched = [], 0
        while self._call(operation, "ПолучитьОперацию", "GetOper") == 1 and len(rows) <= limit:
            self._call(operation, "ВыбратьПроводки", "SelectEntries")
            while self._call(operation, "ПолучитьПроводку", "GetEntry") == 1 and len(rows) <= limit:
                debit = self._serialize(operation.Debit.Account)
                credit = self._serialize(operation.Credit.Account)
                if account and account not in (debit.get("code", ""), credit.get("code", "")):
                    continue
                if matched >= offset:
                    rows.append({"date": self._value(operation, "ДатаОперации", "D"),
                                 "description": self._value(operation, "Содержание", "S"),
                                 "document": self._value(operation, "Документ", "O"),
                                 "debit": debit, "credit": credit,
                                 "debit_subconto": self._subconto(operation.Debit),
                                 "credit_subconto": self._subconto(operation.Credit),
                                 "entries_enabled": bool(self._call(operation, "ВключитьПроводки", "EntriesOn")),
                                 "complex_entry": bool(self._call(operation, "СложнаяПроводка", "ComplexEntry")),
                                 "entry_number": self._call(operation, "НомерПроводки", "EntryNumber"),
                                 "correspondence_number": self._call(operation, "НомерКорреспонденции", "CorrespondenceNumber"),
                                 "amount": self._value(operation, "Сумма", "N"),
                                 "currency": self._value(operation, "Валюта"),
                                 "currency_amount": self._value(operation, "ВалСумма", "N"),
                                 "quantity": self._value(operation, "Количество", "N")})
                matched += 1
        return self._result(rows, limit, offset)

    def _subconto(self, side) -> list[dict]:
        account = side.Account
        return [{"position": index,
                 "kind": self._serialize(self._call(account, "ВидСубконто", "SubcontoKind", index)),
                 "value": self._serialize(self._call(side, "Субконто", "Subconto", index))}
                for index in range(1, int(self._call(account, "КоличествоСубконто", "SubcontoCount")) + 1)]

    def read_accounting_totals(self, date_from, date_to, accounts) -> dict:
        start, end = self._date(date_from, "date_from"), self._date(date_to, "date_to")
        if start > end:
            raise DataAccessError("invalid_period", "date_from не может быть позже date_to.")
        if not isinstance(accounts, list) or not 1 <= len(accounts) <= 500 or any(not isinstance(x, str) or not x for x in accounts):
            raise DataAccessError("invalid_accounts", "accounts должен содержать от 1 до 500 кодов счетов.")
        rows = []
        for code in accounts:
            totals = self._create("БухгалтерскиеИтоги")
            if self._call(totals, "ВыполнитьЗапрос", "DoQuery", start, end, code) == 0:
                raise DataAccessError("totals_failed", f"Не удалось рассчитать итоги по счету {code}.")
            rows.append({"account": code,
                         "opening_debit": self._serialize(self._call(totals, "СНД", "IDB"), "N"),
                         "opening_credit": self._serialize(self._call(totals, "СНК", "ICB"), "N"),
                         "debit_turnover": self._serialize(self._call(totals, "ДО", "TD"), "N"),
                         "credit_turnover": self._serialize(self._call(totals, "КО", "TC"), "N"),
                         "closing_debit": self._serialize(self._call(totals, "СКД", "FDB"), "N"),
                         "closing_credit": self._serialize(self._call(totals, "СКК", "FCB"), "N")})
        return {"rows": rows, "date_from": date_from, "date_to": date_to}

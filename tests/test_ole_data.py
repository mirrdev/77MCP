"""Public read-only OLE adapter contracts using strict fake automation objects."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mcp_1c77.data_runtime import DataAccessError
from mcp_1c77.ole_data import OleReader


METADATA = {
    "name": "Demo",
    "catalogs": [
        {
            "name": "Товары",
            "attributes": [
                {"name": "Цена", "type": "Число"},
                {"name": "Артикул", "type": "Строка"},
            ],
        }
    ],
    "documents": [
        {
            "name": "Продажа",
            "head_attributes": [{"name": "Сумма", "type": "Число"}],
            "table_attributes": [
                {"name": "Товар", "type": "Справочник"},
                {"name": "Количество", "type": "Число"},
            ],
        }
    ],
}


class Reference:
    def __init__(self, encoded="DOC-1", code="001"):
        self.encoded = encoded
        self.Code = code

    def __str__(self):
        return "Документ №1"


class Selection:
    """Expose only selection/read members expected from a 1C aggregate."""

    def __init__(self, rows, next_method):
        self.rows = rows
        self.index = -1
        self.next_method = next_method
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if 0 <= self.index < len(self.rows) and name in self.rows[self.index]:
            return self.rows[self.index][name]
        if name == self.next_method:
            def advance():
                self.calls.append(name)
                self.index += 1
                return 1 if self.index < len(self.rows) else 0
            return advance
        if name.startswith(("Select", "Выбрать")):
            def select(*args):
                self.calls.append((name, args))
                return 1
            return select
        raise AttributeError(name)


class DocumentLines(Selection):
    def __init__(self, rows):
        super().__init__(rows, "GetLine")
        self.found = None

    def FindDocument(self, value):
        self.calls.append(("FindDocument", value))
        self.found = value
        return 1


class Totals:
    def __init__(self):
        self.query = None

    def DoQuery(self, start, end, account):
        self.query = (start, end, account)
        return 1

    def IDB(self): return Decimal("10.10")
    def ICB(self): return Decimal("1.10")
    def TD(self): return Decimal("5.25")
    def TC(self): return Decimal("2.00")
    def FDB(self): return Decimal("13.25")
    def FCB(self): return Decimal("1.00")


class FakeApp:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.created = []
        self.reference = Reference()

    def CreateObject(self, type_name):
        self.created.append(type_name)
        value = self.objects[type_name]
        return value() if callable(value) else value

    def ValueToStringInternal(self, value):
        return value.encoded

    def ValueFromStringInternal(self, value):
        self.reference.encoded = value
        return self.reference

    def ValueTypeStr(self, value):
        return "Документ" if isinstance(value, Reference) else "Значение"


def reader(app=None):
    result = OleReader.__new__(OleReader)
    result._app = app or FakeApp()
    result._metadata = METADATA
    result._catalogs = {item["name"]: item for item in METADATA["catalogs"]}
    result._documents = {item["name"]: item for item in METADATA["documents"]}
    result._document_references = {}
    return result


@pytest.mark.parametrize(
    ("method", "arguments", "code"),
    [
        ("read_catalog", {"name": "Товары;Удалить", "limit": 10}, "invalid_name"),
        ("read_catalog", {"name": "Товары", "fields": ["Удалить"], "limit": 10}, "unknown_field"),
        ("read_catalog", {"name": "Товары", "filters": {"Цена": []}, "limit": 10}, "invalid_filter"),
        ("read_documents", {"name": "Продажа", "date_from": "bad", "date_to": "2024-01-01"}, "invalid_date"),
        ("read_accounts", {"limit": 0}, "invalid_limit"),
    ],
)
def test_validation_happens_before_any_ole_object_is_created(method, arguments, code):
    app = FakeApp()
    instance = reader(app)

    with pytest.raises(DataAccessError) as error:
        getattr(instance, method)(**arguments)

    assert error.value.code == code
    assert app.created == []


def test_only_fixed_read_operations_are_dispatchable():
    instance = reader()

    with pytest.raises(DataAccessError) as error:
        instance.call("write_document", {})

    assert error.value.code == "unsupported_operation"
    assert instance._app.created == []


def test_catalog_filters_pages_lookahead_and_serializes_decimal_by_metadata_type():
    selection = Selection(
        [
            {"Код": "001", "Наименование": "A", "ЭтоГруппа": 0, "ПометкаУдаления": 0,
             "Цена": 1.25, "Артикул": "skip"},
            {"Код": "002", "Наименование": "B", "ЭтоГруппа": 0, "ПометкаУдаления": 0,
             "Цена": 2.50, "Артикул": "keep"},
            {"Код": "003", "Наименование": "C", "ЭтоГруппа": 0, "ПометкаУдаления": 0,
             "Цена": 3.75, "Артикул": "keep"},
            {"Код": "004", "Наименование": "D", "ЭтоГруппа": 0, "ПометкаУдаления": 0,
             "Цена": 4.00, "Артикул": "keep"},
        ],
        "GetItem",
    )
    instance = reader(FakeApp({"Справочник.Товары": selection}))

    result = instance.read_catalog(
        "Товары", fields=["code", "Цена"], filters={"Артикул": "keep"}, limit=1, offset=1
    )

    assert result == {
        "rows": [{"code": "003", "Цена": "3.75"}],
        "has_more": True,
        "next_offset": 2,
        "offset": 1,
        "limit": 1,
    }
    assert instance._app.created == ["Справочник.Товары"]
    assert not any(str(call).lower().startswith(("write", "set", "delete")) for call in selection.calls)


def test_document_lines_accept_canonical_reference_and_return_it_with_page():
    document_reference = Reference("DOC-1")
    documents = Selection(
        [{
            "ТекущийДокумент": lambda: document_reference,
            "НомерДок": "1",
            "ДатаДок": datetime(2024, 1, 15),
        }],
        "GetDocument",
    )
    lines = DocumentLines(
        [
            {"Товар": Reference("CAT-1", "A"), "Количество": 1.5},
            {"Товар": Reference("CAT-2", "B"), "Количество": 2.25},
        ]
    )
    objects = iter((documents, lines))
    instance = reader(FakeApp({"Документ.Продажа": lambda: next(objects)}))

    documents_result = instance.read_documents(
        "Продажа", "2024-01-01", "2024-01-31", fields=["reference"], limit=10
    )
    issued_reference = documents_result["rows"][0]["reference"]["reference"]

    result = instance.read_document_lines(
        "Продажа", issued_reference, fields=["Товар", "Количество"], limit=1, offset=0
    )

    assert result["reference"] == "DOC-1"
    assert result["rows"] == [{
        "Товар": {
            "reference": "CAT-1",
            "presentation": "Документ №1",
            "type": "Справочник",
            "code": "A",
        },
        "Количество": "1.5",
    }]
    assert result["has_more"] is True
    assert lines.found is document_reference


def test_accounting_totals_use_authoritative_russian_als_members():
    created = []

    def make_totals():
        value = Totals()
        created.append(value)
        return value

    instance = reader(FakeApp({"БухгалтерскиеИтоги": make_totals}))

    result = instance.read_accounting_totals("2024-01-01", "2024-01-31", ["10"])

    assert result == {"rows": [{
        "account": "10",
        "opening_debit": "10.10",
        "opening_credit": "1.10",
        "debit_turnover": "5.25",
        "credit_turnover": "2.00",
        "closing_debit": "13.25",
        "closing_credit": "1.00",
    }], "date_from": "2024-01-01", "date_to": "2024-01-31"}
    assert created[0].query == (
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 1, 31, tzinfo=timezone.utc), "10"
    )

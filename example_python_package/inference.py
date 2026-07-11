"""Column type inference: the narrowing ladder over one streaming pass."""

import dataclasses
import datetime
import decimal
import enum
import re
import typing

import sqlalchemy as sa


INTEGER_PATTERN: typing.Final = re.compile(r"^-?\d+$")
BOOLEAN_LITERALS: typing.Final = frozenset({"true", "false"})
INT64_MIN: typing.Final = -(2**63)
INT64_MAX: typing.Final = 2**63 - 1


@typing.final
class ColumnType(enum.StrEnum):
    """Inference ladder, ordered narrowest to widest."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    TEXT = "text"


TYPE_PRIORITY: typing.Final = tuple(ColumnType)


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class ColumnSpec:
    column_name: str
    sql_type: sa.types.TypeEngine[typing.Any]
    is_nullable: bool


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoadReport:
    table_name: str
    inserted_rows: int
    inferred_columns: tuple[ColumnSpec, ...]


@typing.final
class ColumnInference:
    """Mutable accumulator for one column during the single inference pass."""

    __slots__ = (
        "candidate_types",
        "has_any_value",
        "has_empty_cell",
        "max_decimal_scale",
        "max_integer_digits",
    )

    def __init__(self, candidate_types: set[ColumnType]) -> None:
        self.candidate_types = candidate_types
        self.has_empty_cell = False
        self.has_any_value = False
        self.max_integer_digits = 0
        self.max_decimal_scale = 0


def is_empty_cell(cell_value: object) -> bool:
    if cell_value is None:
        return True
    return isinstance(cell_value, str) and not cell_value.strip()


def create_inference_states(column_count: int) -> list[ColumnInference]:
    return [ColumnInference(set(TYPE_PRIORITY)) for _ in range(column_count)]


def observe_row(inference_states: list[ColumnInference], data_row: tuple[object, ...]) -> None:
    for one_cell_value, one_column_state in zip(data_row, inference_states, strict=False):
        if is_empty_cell(one_cell_value):
            one_column_state.has_empty_cell = True
            continue
        one_column_state.has_any_value = True
        one_column_state.candidate_types &= classify_value(one_cell_value)
        collect_decimal_shape(one_column_state, one_cell_value)


def build_column_specs(
    header_names: tuple[str, ...],
    inference_states: list[ColumnInference],
) -> tuple[ColumnSpec, ...]:
    return tuple(
        ColumnSpec(
            column_name=one_column_name,
            sql_type=build_sql_type(resolve_column_type(one_column_state), one_column_state),
            is_nullable=one_column_state.has_empty_cell or not one_column_state.has_any_value,
        )
        for one_column_name, one_column_state in zip(header_names, inference_states, strict=False)
    )


def resolve_column_type(column_state: ColumnInference) -> ColumnType:
    if not column_state.has_any_value:
        return ColumnType.TEXT
    return next(one_candidate for one_candidate in TYPE_PRIORITY if one_candidate in column_state.candidate_types)


def build_sql_type(column_type: ColumnType, column_state: ColumnInference) -> sa.types.TypeEngine[typing.Any]:
    if column_type is ColumnType.BOOLEAN:
        return sa.Boolean()
    if column_type is ColumnType.INTEGER:
        return sa.BigInteger()
    if column_type is ColumnType.DECIMAL:
        decimal_scale: typing.Final = column_state.max_decimal_scale
        return sa.Numeric(max(column_state.max_integer_digits + decimal_scale, 1), decimal_scale)
    if column_type is ColumnType.DATE:
        return sa.Date()
    if column_type is ColumnType.DATETIME:
        return sa.DateTime()
    return sa.Text()


def classify_value(cell_value: object) -> frozenset[ColumnType]:
    if isinstance(cell_value, bool):
        return frozenset({ColumnType.BOOLEAN, ColumnType.TEXT})
    if isinstance(cell_value, int):
        return classify_native_integer(cell_value)
    if isinstance(cell_value, (float, decimal.Decimal)):
        return frozenset({ColumnType.DECIMAL, ColumnType.TEXT})
    if isinstance(cell_value, datetime.datetime):
        return frozenset({ColumnType.DATETIME, ColumnType.TEXT})
    if isinstance(cell_value, datetime.date):
        return frozenset({ColumnType.DATE, ColumnType.DATETIME, ColumnType.TEXT})
    return classify_text(str(cell_value))


def classify_text(text_value: str) -> frozenset[ColumnType]:
    stripped: typing.Final = text_value.strip()
    matched_types: typing.Final = {ColumnType.TEXT}
    if stripped.lower() in BOOLEAN_LITERALS:
        matched_types.add(ColumnType.BOOLEAN)
    if INTEGER_PATTERN.match(stripped) and is_within_int64(int(stripped)):
        matched_types.add(ColumnType.INTEGER)
    if parse_decimal_text(stripped) is not None:
        matched_types.add(ColumnType.DECIMAL)
    if is_iso_date(stripped):
        matched_types.add(ColumnType.DATE)
    if is_iso_datetime(stripped):
        matched_types.add(ColumnType.DATETIME)
    return frozenset(matched_types)


def convert_cell_value(sql_type: sa.types.TypeEngine[typing.Any], raw_value: object) -> object:
    if is_empty_cell(raw_value):
        return None
    for one_candidate_type, one_converter in TYPE_COERCERS:
        if isinstance(sql_type, one_candidate_type):
            return one_converter(raw_value)
    return str(raw_value)


def convert_to_decimal(cell_value: object) -> decimal.Decimal | None:
    if isinstance(cell_value, bool):
        return None
    if isinstance(cell_value, int):
        return decimal.Decimal(cell_value)
    if isinstance(cell_value, float):
        return decimal.Decimal(str(cell_value))
    if isinstance(cell_value, decimal.Decimal):
        return cell_value if cell_value.is_finite() else None
    if isinstance(cell_value, str):
        return parse_decimal_text(cell_value)
    return None


def parse_decimal_text(text_value: str) -> decimal.Decimal | None:
    stripped: typing.Final = text_value.strip()
    if not stripped:
        return None
    try:
        parsed_number: typing.Final = decimal.Decimal(stripped)
    except decimal.InvalidOperation:
        return None
    return parsed_number if parsed_number.is_finite() else None


def measure_decimal_shape(cell_value: object) -> tuple[int, int] | None:
    numeric_value: typing.Final = convert_to_decimal(cell_value)
    if numeric_value is None:
        return None
    _, digits, exponent = numeric_value.as_tuple()
    if not isinstance(exponent, int):
        return None
    if exponent >= 0:
        return (len(digits) + exponent, 0)
    decimal_scale: typing.Final = -exponent
    return (max(1, len(digits) - decimal_scale), decimal_scale)


def collect_decimal_shape(column_state: ColumnInference, cell_value: object) -> None:
    measurement: typing.Final = measure_decimal_shape(cell_value)
    if measurement is None:
        return
    integer_digits, decimal_scale = measurement
    column_state.max_integer_digits = max(column_state.max_integer_digits, integer_digits)
    column_state.max_decimal_scale = max(column_state.max_decimal_scale, decimal_scale)


def classify_native_integer(cell_value: int) -> frozenset[ColumnType]:
    if is_within_int64(cell_value):
        return frozenset({ColumnType.INTEGER, ColumnType.DECIMAL, ColumnType.TEXT})
    return frozenset({ColumnType.DECIMAL, ColumnType.TEXT})


def is_within_int64(integer_value: int) -> bool:
    return INT64_MIN <= integer_value <= INT64_MAX


def is_iso_date(text_value: str) -> bool:
    try:
        datetime.date.fromisoformat(text_value)
    except ValueError:
        return False
    return True


def is_iso_datetime(text_value: str) -> bool:
    try:
        datetime.datetime.fromisoformat(text_value)
    except ValueError:
        return False
    return True


def convert_boolean(raw_value: object) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() == "true"


def convert_date(raw_value: object) -> datetime.date:
    if isinstance(raw_value, datetime.datetime):
        return raw_value.date()
    if isinstance(raw_value, datetime.date):
        return raw_value
    return datetime.date.fromisoformat(str(raw_value).strip())


def convert_datetime(raw_value: object) -> datetime.datetime:
    if isinstance(raw_value, datetime.datetime):
        return raw_value
    if isinstance(raw_value, datetime.date):
        return datetime.datetime.combine(raw_value, datetime.time())
    return datetime.datetime.fromisoformat(str(raw_value).strip())


def convert_integer(raw_value: object) -> int:
    if isinstance(raw_value, int):
        return raw_value
    return int(str(raw_value).strip())


TYPE_COERCERS: typing.Final = (
    (sa.Boolean, convert_boolean),
    (sa.BigInteger, convert_integer),
    (sa.Numeric, convert_to_decimal),
    (sa.DateTime, convert_datetime),
    (sa.Date, convert_date),
)


def run_self_check() -> None:
    """Runnable self-check: fails if the ladder breaks."""
    header_names: typing.Final = ("flag", "count", "amount", "when")
    sample_rows: typing.Final[list[tuple[object, ...]]] = [
        ("true", "1", "1.5", "2020-01-01"),
        ("false", "20200101", "12345678901234567890", "2020-01-02"),
    ]
    inference_states: typing.Final = create_inference_states(len(header_names))
    for one_data_row in sample_rows:
        observe_row(inference_states, one_data_row)
    resolved_types: typing.Final = {
        one_spec.column_name: type(one_spec.sql_type).__name__
        for one_spec in build_column_specs(header_names, inference_states)
    }
    assert resolved_types["flag"] == "Boolean", resolved_types  # noqa: S101
    assert resolved_types["count"] == "BigInteger", resolved_types  # noqa: S101
    assert resolved_types["amount"] == "Numeric", resolved_types  # noqa: S101
    assert resolved_types["when"] == "Date", resolved_types  # noqa: S101


if __name__ == "__main__":
    run_self_check()

import collections.abc
import csv
import datetime
import decimal
import typing

import openpyxl
import pytest

import example_python_package as tableload
from example_python_package import errors, load_file


if typing.TYPE_CHECKING:
    import pathlib

    from example_python_package.inference import ColumnSpec


ReadTable = collections.abc.Callable[[str, str], list[dict[str, object]]]


def _write_csv(csv_path: pathlib.Path, table_rows: list[list[object]]) -> pathlib.Path:
    with csv_path.open("w", newline="", encoding="utf-8") as csv_handle:
        csv.writer(csv_handle).writerows(table_rows)
    return csv_path


def _collect_column_types(column_specs: tuple[ColumnSpec, ...]) -> dict[str, str]:
    return {one_spec.column_name: type(one_spec.sql_type).__name__ for one_spec in column_specs}


def test_should_infer_type_ladder_across_borders(
    tmp_path: pathlib.Path,
    database_url: str,
    read_table: ReadTable,
) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(
        tmp_path / "sample.csv",
        [
            ["flag", "count", "huge", "amount", "day", "moment", "note"],
            ["true", "1", "1", "1.50", "2020-01-01", "2020-01-01T10:00:00", "hello"],
            ["false", "0", "12345678901234567890", "12.5", "2020-01-02", "2020-01-02T11:30:00", "world"],
        ],
    )

    # Act
    load_report: typing.Final = load_file(source_file, database_url=database_url)

    # Assert
    assert _collect_column_types(load_report.inferred_columns) == {
        "flag": "Boolean",
        "count": "BigInteger",
        "huge": "Numeric",
        "amount": "Numeric",
        "day": "Date",
        "moment": "DateTime",
        "note": "Text",
    }
    assert load_report.inserted_rows == 2
    loaded_rows: typing.Final = read_table(database_url, "sample")
    assert loaded_rows[0]["flag"] is True
    assert loaded_rows[0]["amount"] == decimal.Decimal("1.50")
    assert loaded_rows[1]["day"] == datetime.date(2020, 1, 2)
    assert loaded_rows[1]["moment"] == datetime.datetime(2020, 1, 2, 11, 30, 0)  # noqa: DTZ001


def test_should_not_confuse_zero_one_with_boolean(tmp_path: pathlib.Path, database_url: str) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(tmp_path / "nums.csv", [["value"], ["0"], ["1"]])

    # Act
    load_report: typing.Final = load_file(source_file, database_url=database_url)

    # Assert
    assert _collect_column_types(load_report.inferred_columns) == {"value": "BigInteger"}


def test_should_treat_all_empty_column_as_nullable_text(tmp_path: pathlib.Path, database_url: str) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(tmp_path / "blank.csv", [["given", "blank"], ["x", ""], ["y", ""]])

    # Act
    load_report: typing.Final = load_file(source_file, database_url=database_url)

    # Assert
    nullable_spec: typing.Final = next(
        one_spec for one_spec in load_report.inferred_columns if one_spec.column_name == "blank"
    )
    assert type(nullable_spec.sql_type).__name__ == "Text"
    assert nullable_spec.is_nullable is True


def test_should_reject_json_container_cells_and_skip_insert(tmp_path: pathlib.Path, database_url: str) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(
        tmp_path / "bad.csv",
        [["name", "tags"], ["alice", '["a", "b"]'], ["bob", "ok"]],
    )

    # Act / Assert
    with pytest.raises(errors.AtomicityError) as raised_error:
        load_file(source_file, database_url=database_url)
    first_violation: typing.Final = raised_error.value.violations[0]
    assert first_violation.row_number == 1
    assert first_violation.column_name == "tags"


def test_should_fail_when_table_exists_by_default(tmp_path: pathlib.Path, database_url: str) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(tmp_path / "dup.csv", [["value"], ["1"]])
    load_file(source_file, database_url=database_url)

    # Act / Assert
    with pytest.raises(errors.TableAlreadyExistsError):
        load_file(source_file, database_url=database_url)


def test_should_replace_and_append_existing_table(
    tmp_path: pathlib.Path,
    database_url: str,
    read_table: ReadTable,
) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(tmp_path / "grow.csv", [["value"], ["1"], ["2"]])
    load_file(source_file, database_url=database_url)

    # Act
    load_file(source_file, database_url=database_url, if_exists="replace")

    # Assert
    assert load_file(source_file, database_url=database_url, if_exists="append").inserted_rows == 2
    assert len(read_table(database_url, "grow")) == 4


def test_should_reject_append_with_missing_columns(tmp_path: pathlib.Path, database_url: str) -> None:
    # Arrange
    load_file(
        _write_csv(tmp_path / "base.csv", [["value"], ["1"]]),
        database_url=database_url,
        table_name="shared",
    )
    wider_file: typing.Final = _write_csv(tmp_path / "wider.csv", [["value", "extra"], ["1", "2"]])

    # Act / Assert
    with pytest.raises(errors.SchemaMismatchError):
        load_file(wider_file, database_url=database_url, table_name="shared", if_exists="append")


def test_should_synthesize_column_names_without_header(
    tmp_path: pathlib.Path,
    database_url: str,
    read_table: ReadTable,
) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(tmp_path / "raw.csv", [["1", "alice"], ["2", "bob"]])

    # Act
    load_report: typing.Final = load_file(source_file, database_url=database_url, has_header=False)

    # Assert
    assert [one_spec.column_name for one_spec in load_report.inferred_columns] == ["col_1", "col_2"]
    assert load_report.inserted_rows == 2
    assert read_table(database_url, "raw")[0]["col_2"] == "alice"


def test_should_load_xlsx_with_native_types(
    tmp_path: pathlib.Path,
    database_url: str,
    read_table: ReadTable,
) -> None:
    # Arrange
    workbook: typing.Final = openpyxl.Workbook()
    worksheet: typing.Final = workbook.active
    worksheet.append(["label", "score", "when"])
    worksheet.append(["alpha", 10, datetime.datetime(2021, 5, 1, 9, 0, 0)])  # noqa: DTZ001
    xlsx_path: typing.Final = tmp_path / "book.xlsx"
    workbook.save(xlsx_path)

    # Act
    load_report: typing.Final = load_file(xlsx_path, database_url=database_url)

    # Assert
    assert _collect_column_types(load_report.inferred_columns) == {
        "label": "Text",
        "score": "BigInteger",
        "when": "DateTime",
    }
    assert read_table(database_url, "book")[0]["score"] == 10


def test_should_reject_unknown_extension(tmp_path: pathlib.Path, database_url: str) -> None:
    # Arrange
    source_file: typing.Final = tmp_path / "data.json"
    source_file.write_text("{}", encoding="utf-8")

    # Act / Assert
    with pytest.raises(errors.UnsupportedFormatError):
        load_file(source_file, database_url=database_url)


def test_public_api_exposes_load_file() -> None:
    assert tableload.load_file is load_file

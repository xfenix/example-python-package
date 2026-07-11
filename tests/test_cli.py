import csv
import typing

from example_python_package import cli
from example_python_package.inference import run_self_check as run_inference_self_check
from example_python_package.validation import run_self_check as run_validation_self_check


if typing.TYPE_CHECKING:
    import pathlib

    import pytest


def _write_csv(csv_path: pathlib.Path, table_rows: list[list[object]]) -> pathlib.Path:
    with csv_path.open("w", newline="", encoding="utf-8") as csv_handle:
        csv.writer(csv_handle).writerows(table_rows)
    return csv_path


def test_cli_load_returns_success(
    tmp_path: pathlib.Path,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(tmp_path / "cli.csv", [["value"], ["1"], ["2"]])

    # Act
    exit_code: typing.Final = cli.main(["load", str(source_file), "--db", database_url])

    # Assert
    assert exit_code == cli.EXIT_SUCCESS
    assert "Loaded 2 row(s)" in capsys.readouterr().out


def test_cli_reports_atomicity_violation(
    tmp_path: pathlib.Path,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    source_file: typing.Final = _write_csv(tmp_path / "cli.csv", [["tags"], ['{"a": 1}']])

    # Act
    exit_code: typing.Final = cli.main(["load", str(source_file), "--db", database_url])

    # Assert
    assert exit_code == cli.EXIT_ATOMICITY
    assert "atomicity" in capsys.readouterr().err.lower()


def test_cli_requires_database_url(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    monkeypatch.delenv("TABLELOAD_DB_URL", raising=False)
    source_file: typing.Final = _write_csv(tmp_path / "cli.csv", [["value"], ["1"]])

    # Act
    exit_code: typing.Final = cli.main(["load", str(source_file)])

    # Assert
    assert exit_code == cli.EXIT_USAGE
    assert "database URL" in capsys.readouterr().err


def test_module_self_checks_pass() -> None:
    # Act / Assert (self-checks raise on failure)
    run_inference_self_check()
    run_validation_self_check()

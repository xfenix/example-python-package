"""Thin CLI wrapper: parse args, call the library, map errors to exit codes."""

import argparse
import sys
import typing

import example_python_package.config as config_module
import example_python_package.errors as errors_module
import example_python_package.loader as loader_module


if typing.TYPE_CHECKING:
    import example_python_package.inference as inference_module


EXIT_SUCCESS: typing.Final = 0
EXIT_USAGE: typing.Final = 1
EXIT_ATOMICITY: typing.Final = 2
VIOLATION_PREVIEW_LIMIT: typing.Final = 20


def main(command_args: list[str] | None = None) -> int:
    namespace: typing.Final = _build_parser().parse_args(command_args)
    database_url: typing.Final = config_module.resolve_database_url(namespace.db)
    if not database_url:
        _write_error("No database URL: pass --db or set TABLELOAD_DB_URL.")
        return EXIT_USAGE
    return _run_load(namespace, database_url)


def _run_load(namespace: argparse.Namespace, database_url: str) -> int:
    try:
        load_report: typing.Final = loader_module.load_file(
            namespace.file,
            database_url=database_url,
            table_name=namespace.table,
            if_exists=namespace.if_exists,
            has_header=not namespace.no_header,
        )
    except errors_module.AtomicityError as atomicity_error:
        _render_violations(atomicity_error)
        return EXIT_ATOMICITY
    except errors_module.TableLoadError as load_error:
        _write_error(str(load_error))
        return EXIT_USAGE
    _render_success(load_report)
    return EXIT_SUCCESS


def _build_parser() -> argparse.ArgumentParser:
    argument_parser: typing.Final = argparse.ArgumentParser(
        prog="tableload",
        description="Load CSV/XLSX into one flat table.",
    )
    load_parser: typing.Final = argument_parser.add_subparsers(dest="command", required=True).add_parser(
        "load",
        help="Infer types and load a file into a table.",
    )
    load_parser.add_argument("file", help="Path to the .csv or .xlsx file.")
    load_parser.add_argument("--db", default=None, help="SQLAlchemy database URL (else TABLELOAD_DB_URL).")
    load_parser.add_argument("--table", default=None, help="Target table name (default: file stem).")
    load_parser.add_argument(
        "--if-exists",
        dest="if_exists",
        choices=("fail", "append", "replace"),
        default="fail",
    )
    load_parser.add_argument("--no-header", dest="no_header", action="store_true", help="File has no header row.")
    return argument_parser


def _render_success(load_report: inference_module.LoadReport) -> None:
    column_summary: typing.Final = ", ".join(
        f"{one_spec.column_name}:{type(one_spec.sql_type).__name__}" for one_spec in load_report.inferred_columns
    )
    sys.stdout.write(f"Loaded {load_report.inserted_rows} row(s) into {load_report.table_name!r} [{column_summary}].\n")


def _render_violations(atomicity_error: errors_module.AtomicityError) -> None:
    _write_error(str(atomicity_error))
    for one_violation in atomicity_error.violations[:VIOLATION_PREVIEW_LIMIT]:
        _write_error(
            f"  row {one_violation.row_number}, column {one_violation.column_name!r}: {one_violation.offending_value}",
        )


def _write_error(error_message: str) -> None:
    sys.stderr.write(f"{error_message}\n")


if __name__ == "__main__":
    raise SystemExit(main())

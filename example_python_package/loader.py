"""Orchestrator: two passes over the reader, one transaction, if-exists policy."""

import pathlib
import typing

import sqlalchemy as sa
import sqlalchemy.exc
import stamina

import example_python_package.errors as errors_module
import example_python_package.inference as inference_module
import example_python_package.readers as readers_module
import example_python_package.schema as schema_module
import example_python_package.validation as validation_module


DEFAULT_BATCH_SIZE: typing.Final = 10_000
VIOLATION_CAP: typing.Final = 1_000
CONNECT_ATTEMPTS: typing.Final = 3

IfExistsPolicy = typing.Literal["fail", "append", "replace"]


def load_file(  # noqa: PLR0913
    file_path: str | pathlib.Path,
    *,
    database_url: str,
    table_name: str | None = None,
    if_exists: IfExistsPolicy = "fail",
    has_header: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> inference_module.LoadReport:
    source_path: typing.Final = pathlib.Path(file_path)
    row_reader: typing.Final = readers_module.build_reader(source_path, has_header=has_header)
    sql_engine: typing.Final = sa.create_engine(database_url)
    try:
        return _load_with_engine(
            row_reader,
            sql_engine=sql_engine,
            table_name=table_name or source_path.stem,
            if_exists=if_exists,
            batch_size=batch_size,
        )
    finally:
        sql_engine.dispose()


def _load_with_engine(
    row_reader: readers_module.RowReader,
    *,
    sql_engine: sa.Engine,
    table_name: str,
    if_exists: IfExistsPolicy,
    batch_size: int,
) -> inference_module.LoadReport:
    column_specs: typing.Final = _build_validated_columns(row_reader)
    with _connect_with_retry(sql_engine) as connection, connection.begin():
        target_table: typing.Final = _prepare_table(
            connection,
            metadata=sa.MetaData(),
            table_name=table_name,
            column_specs=column_specs,
            if_exists=if_exists,
        )
        inserted_rows: typing.Final = _write_rows_in_batches(
            connection,
            target_table=target_table,
            row_reader=row_reader,
            column_specs=column_specs,
            batch_size=batch_size,
        )
    return inference_module.LoadReport(
        table_name=table_name,
        inserted_rows=inserted_rows,
        inferred_columns=column_specs,
    )


def _build_validated_columns(row_reader: readers_module.RowReader) -> tuple[inference_module.ColumnSpec, ...]:
    header_names: typing.Final = row_reader.header_names
    inference_states: typing.Final = inference_module.create_inference_states(len(header_names))
    violations: typing.Final[list[validation_module.AtomicityViolation]] = []
    for one_row_number, one_data_row in enumerate(row_reader.iter_rows(), start=1):
        inference_module.observe_row(inference_states, one_data_row)
        violations.extend(
            validation_module.find_row_violations(one_row_number, header_names=header_names, data_row=one_data_row),
        )
        if len(violations) >= VIOLATION_CAP:
            break
    if violations:
        raise errors_module.AtomicityError(violations=tuple(violations))
    return inference_module.build_column_specs(header_names, inference_states)


def _connect_with_retry(sql_engine: sa.Engine) -> sa.Connection:
    for one_attempt in stamina.retry_context(on=sa.exc.OperationalError, attempts=CONNECT_ATTEMPTS):
        with one_attempt:
            return sql_engine.connect()
    raise RuntimeError("Failed to establish a database connection.")  # pragma: no cover


def _prepare_table(
    connection: sa.Connection,
    *,
    metadata: sa.MetaData,
    table_name: str,
    column_specs: tuple[inference_module.ColumnSpec, ...],
    if_exists: IfExistsPolicy,
) -> sa.Table:
    table_exists: typing.Final = sa.inspect(connection).has_table(table_name)
    if if_exists == "append":
        return _prepare_for_append(
            connection,
            metadata=metadata,
            table_name=table_name,
            column_specs=column_specs,
            table_exists=table_exists,
        )
    if if_exists == "replace" and table_exists:
        _remove_existing_table(connection, table_name)
    elif table_exists:
        raise errors_module.TableAlreadyExistsError(f"Table {table_name!r} already exists.")
    return _create_table(connection, metadata=metadata, table_name=table_name, column_specs=column_specs)


def _prepare_for_append(
    connection: sa.Connection,
    *,
    metadata: sa.MetaData,
    table_name: str,
    column_specs: tuple[inference_module.ColumnSpec, ...],
    table_exists: bool,
) -> sa.Table:
    if not table_exists:
        return _create_table(connection, metadata=metadata, table_name=table_name, column_specs=column_specs)
    existing_table: typing.Final = schema_module.load_existing_table(
        table_name,
        connection=connection,
        metadata=metadata,
    )
    _ensure_columns_present(table_name, existing_table=existing_table, column_specs=column_specs)
    return existing_table


def _ensure_columns_present(
    table_name: str,
    *,
    existing_table: sa.Table,
    column_specs: tuple[inference_module.ColumnSpec, ...],
) -> None:
    missing_names: typing.Final = frozenset(one_spec.column_name for one_spec in column_specs).difference(
        existing_table.columns.keys(),
    )
    if missing_names:
        raise errors_module.SchemaMismatchError(
            f"Table {table_name!r} is missing columns: {', '.join(sorted(missing_names))}.",
        )


def _create_table(
    connection: sa.Connection,
    *,
    metadata: sa.MetaData,
    table_name: str,
    column_specs: tuple[inference_module.ColumnSpec, ...],
) -> sa.Table:
    target_table: typing.Final = schema_module.build_table(table_name, column_specs=column_specs, metadata=metadata)
    target_table.create(connection)
    return target_table


def _remove_existing_table(connection: sa.Connection, table_name: str) -> None:
    sa.Table(table_name, sa.MetaData(), autoload_with=connection).drop(connection)


def _write_rows_in_batches(
    connection: sa.Connection,
    *,
    target_table: sa.Table,
    row_reader: readers_module.RowReader,
    column_specs: tuple[inference_module.ColumnSpec, ...],
    batch_size: int,
) -> int:
    insert_statement: typing.Final = sa.insert(target_table)
    pending_batch: typing.Final[list[dict[str, object]]] = []
    inserted_rows = 0
    for one_data_row in row_reader.iter_rows():
        pending_batch.append(_build_row_mapping(column_specs, one_data_row))
        if len(pending_batch) >= batch_size:
            connection.execute(insert_statement, pending_batch)
            inserted_rows += len(pending_batch)
            pending_batch.clear()
    if pending_batch:
        connection.execute(insert_statement, pending_batch)
        inserted_rows += len(pending_batch)
    return inserted_rows


def _build_row_mapping(
    column_specs: tuple[inference_module.ColumnSpec, ...],
    data_row: tuple[object, ...],
) -> dict[str, object]:
    return {
        one_spec.column_name: inference_module.convert_cell_value(one_spec.sql_type, one_cell_value)
        for one_spec, one_cell_value in zip(column_specs, data_row, strict=False)
    }

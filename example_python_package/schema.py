"""Table construction and reflection over SQLAlchemy Core."""

import typing

import sqlalchemy as sa


if typing.TYPE_CHECKING:
    import example_python_package.inference as inference_module


def build_table(
    table_name: str,
    *,
    column_specs: tuple[inference_module.ColumnSpec, ...],
    metadata: sa.MetaData,
) -> sa.Table:
    return sa.Table(
        table_name,
        metadata,
        *[
            sa.Column(one_spec.column_name, one_spec.sql_type, nullable=one_spec.is_nullable)
            for one_spec in column_specs
        ],
    )


def load_existing_table(table_name: str, *, connection: sa.Connection, metadata: sa.MetaData) -> sa.Table:
    return sa.Table(table_name, metadata, autoload_with=connection)

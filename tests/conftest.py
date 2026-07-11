import typing

import pytest
import sqlalchemy as sa


if typing.TYPE_CHECKING:
    import collections.abc
    import pathlib


@pytest.fixture
def database_url(tmp_path: pathlib.Path) -> str:
    return f"sqlite:///{tmp_path / 'tableload.db'}"


@pytest.fixture
def read_table() -> collections.abc.Callable[[str, str], list[dict[str, object]]]:
    def _read_table(target_url: str, table_name: str) -> list[dict[str, object]]:
        sql_engine: typing.Final = sa.create_engine(target_url)
        try:
            reflected_table: typing.Final = sa.Table(table_name, sa.MetaData(), autoload_with=sql_engine)
            with sql_engine.connect() as connection:
                return [
                    dict(one_row_mapping)
                    for one_row_mapping in connection.execute(sa.select(reflected_table)).mappings()
                ]
        finally:
            sql_engine.dispose()

    return _read_table

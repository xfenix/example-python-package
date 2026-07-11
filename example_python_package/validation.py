"""Atomicity validation: a cell is non-atomic if it is a JSON array or object."""

import dataclasses
import json
import typing


JSON_CONTAINER_PREFIXES: typing.Final = ("[", "{")


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class AtomicityViolation:
    row_number: int
    column_name: str
    offending_value: str


def find_row_violations(
    row_number: int,
    *,
    header_names: tuple[str, ...],
    data_row: tuple[object, ...],
) -> list[AtomicityViolation]:
    return [
        AtomicityViolation(row_number=row_number, column_name=one_column_name, offending_value=str(one_cell_value))
        for one_column_name, one_cell_value in zip(header_names, data_row, strict=False)
        if check_non_atomic_cell(one_cell_value)
    ]


def check_non_atomic_cell(cell_value: object) -> bool:
    if not isinstance(cell_value, str):
        return False
    stripped: typing.Final = cell_value.strip()
    if not stripped or not stripped.startswith(JSON_CONTAINER_PREFIXES):
        return False
    try:
        parsed_value: typing.Final = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed_value, (list, dict))


def run_self_check() -> None:
    """Runnable self-check: fails if the JSON container detector breaks."""
    assert check_non_atomic_cell("[1, 2, 3]")  # noqa: S101
    assert check_non_atomic_cell('{"a": 1}')  # noqa: S101
    assert not check_non_atomic_cell("42")  # noqa: S101
    assert not check_non_atomic_cell("hello")  # noqa: S101
    assert not check_non_atomic_cell("[unclosed")  # noqa: S101
    assert not check_non_atomic_cell(42)  # noqa: S101


if __name__ == "__main__":
    run_self_check()

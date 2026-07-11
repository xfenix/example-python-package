"""Typed failures raised by the loader; the CLI maps them to exit codes."""

import typing


if typing.TYPE_CHECKING:
    import example_python_package.validation as validation_module


class TableLoadError(Exception):
    """Base failure for the table loader."""


@typing.final
class UnsupportedFormatError(TableLoadError):
    """Raised when the input file extension has no reader."""


@typing.final
class TableAlreadyExistsError(TableLoadError):
    """Raised when the target table exists and if-exists is fail."""


@typing.final
class SchemaMismatchError(TableLoadError):
    """Raised when appending to a table missing some file columns."""


@typing.final
class AtomicityError(TableLoadError):
    """Raised when the file holds non-atomic (JSON array/object) cells."""

    def __init__(self, *, violations: tuple[validation_module.AtomicityViolation, ...]) -> None:
        self.violations = violations
        super().__init__(f"Found {len(violations)} atomicity violation(s).")

"""tableload: stream a CSV/XLSX file into one flat relational table."""

from example_python_package import errors
from example_python_package.inference import ColumnSpec, LoadReport
from example_python_package.loader import load_file
from example_python_package.validation import AtomicityViolation


__all__ = [
    "AtomicityViolation",
    "ColumnSpec",
    "LoadReport",
    "errors",
    "load_file",
]

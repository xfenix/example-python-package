# example-python-package

[![coverage](https://raw.githubusercontent.com/xfenix/example-python-package/gh-pages/badges/coverage.svg)](https://github.com/xfenix/example-python-package/actions/workflows/ci.yml)

`tableload` streams a CSV/XLSX file into one flat SQL table: it infers column types, validates every cell is atomic, and inserts in batches inside a single transaction. Built to the [community-of-python/pylines](https://github.com/community-of-python/pylines) standards, with `ty` in place of mypy.

## Quickstart

```bash
uv add example-python-package   # or: pip install example-python-package

# CLI
export TABLELOAD_DB_URL=sqlite:///data.db   # or pass --db
tableload load people.csv                    # table name defaults to the file stem
```

```python
from example_python_package import load_file

report = load_file("people.csv", database_url="sqlite:///data.db")
print(report.inserted_rows, report.table_name)
```

## CLI

```
tableload load FILE [--db URL] [--table NAME] [--if-exists fail|append|replace] [--no-header]
```

`--db` overrides `TABLELOAD_DB_URL`. Exit codes: `0` success, `1` usage/load error, `2` atomicity violation (offending rows printed to stderr).

## Development

```bash
just install   # sync deps + install pre-commit hooks
just check     # lint + type check + tests (the full local gate)
just fix       # apply all autofixes
```

Everything CI runs is a `just` recipe. See `justfile` for the full list.

## Release

Publishing to PyPI happens automatically when a semver tag is pushed:

```bash
git tag 1.2.3 && git push origin 1.2.3
```

The version in `pyproject.toml` stays `0`; the real version is taken from the tag at publish time.

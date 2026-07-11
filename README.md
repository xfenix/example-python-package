# example-python-package

A simple Python package built to the [community-of-python/pylines](https://github.com/community-of-python/pylines) standards, with `ty` in place of mypy for type checking.

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

"""Runtime configuration: database URL from a flag or the environment."""

import typing

import pydantic
import pydantic_settings


@typing.final
class TableLoadSettings(pydantic_settings.BaseSettings):
    database_url: str | None = pydantic.Field(default=None, validation_alias="TABLELOAD_DB_URL")


def resolve_database_url(explicit_url: str | None) -> str | None:
    if explicit_url:
        return explicit_url
    return TableLoadSettings().database_url

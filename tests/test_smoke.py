import typing

from example_python_package import build_greeting


def test_should_build_greeting_with_name() -> None:
    # Arrange
    person_name: typing.Final = "World"

    # Act
    greeting_result: typing.Final = build_greeting(person_name)

    # Assert
    assert greeting_result == "Hello, World!"

"""Tool schema generation from type hints and docstrings — the contract with the LLM."""
import pytest

from voice_agent import tools
from voice_agent.schema import to_schema


@pytest.fixture(scope="module")
def schemas():
    return {f.__name__: to_schema(f) for f in tools.ALL}


def test_every_tool_gets_a_schema(schemas):
    assert set(schemas) == {f.__name__ for f in tools.ALL}


def test_optional_parameter_is_not_required(schemas):
    """`temperature: int | None = None` must map to integer and stay out of required."""
    s = schemas["set_ac"]
    assert s.required == ["on"]
    assert s.properties["temperature"]["type"] == "integer"
    assert s.properties["on"]["type"] == "boolean"


def test_required_parameters(schemas):
    assert schemas["set_window"].required == ["position", "opening"]


def test_descriptions_come_from_the_docstring(schemas):
    """This text is what the model reads — losing it means the model guesses."""
    assert "16-30" in schemas["set_ac"].properties["temperature"]["description"]
    assert "driver" in schemas["set_window"].properties["position"]["description"]


def test_tool_description_excludes_the_args_block(schemas):
    for name, s in schemas.items():
        assert "Args:" not in s.description, name
        assert s.description, f"{name} has no description"


@pytest.mark.parametrize("name", ["set_ac", "set_fan", "set_window", "search_manual"])
def test_every_parameter_is_described(schemas, name):
    for arg, prop in schemas[name].properties.items():
        assert prop["description"] != arg, f"{name}.{arg} has no docstring description"

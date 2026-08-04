"""Generate LLM tool schemas from plain Python functions.

This is the only boundary between `tools/` (pure Python) and Pipecat. Because of
it, adding a tool means writing one function with type hints and a Google-style
docstring — nothing else.
"""
import inspect
import re
import typing

from pipecat.adapters.schemas.function_schema import FunctionSchema

_TYPES = {bool: "boolean", int: "integer", str: "string", float: "number"}


def to_schema(fn) -> FunctionSchema:
    """Read `fn`'s signature and docstring, return a FunctionSchema.

    The docstring's first line becomes the tool description and each `Args:` entry
    becomes a parameter description — so the wording in a docstring is the contract
    with the LLM, and changing it changes model behaviour.
    """
    doc = inspect.getdoc(fn) or ""
    head, _, args_block = doc.partition("Args:")
    arg_docs = dict(re.findall(r"^\s*(\w+):\s*(.+?)(?=\n\s*\w+:|\Z)", args_block, re.S | re.M))
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        # `int | None` resolves to int; anything unrecognised degrades to string.
        base = next((t for t in typing.get_args(hints[name]) or [hints[name]] if t in _TYPES), str)
        props[name] = {"type": _TYPES[base],
                       "description": " ".join(arg_docs.get(name, name).split())}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return FunctionSchema(name=fn.__name__, description=head.strip().split("\n")[0],
                          properties=props, required=required)

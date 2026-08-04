"""Tool registry and dispatch.

Adding a tool means adding one function to a submodule (`vehicle`, `knowledge`,
`web`) and listing it in that module's `TOOLS`. This file does not change, and
neither does the pipeline.
"""
import typing

from . import knowledge, vehicle, web

ALL = [*vehicle.TOOLS, *knowledge.TOOLS, *web.TOOLS]
BY_NAME = {f.__name__: f for f in ALL}

if len(BY_NAME) != len(ALL):
    # Not an assert: `python -O` strips those, and a silently shadowed tool is
    # far worse than a startup crash.
    raise RuntimeError(f"duplicate tool names across modules: {[f.__name__ for f in ALL]}")


def dispatch(name: str, args: dict) -> dict:
    """Call a tool by name.

    Never raises. An LLM producing a wrong tool name, a wrong argument type, or a
    missing argument is routine; returning an error dict lets the model correct
    itself on the next turn instead of killing the pipeline.
    """
    fn = BY_NAME.get(name)
    if fn is None:
        return {"status": "error", "message": f"Không có tool tên '{name}'"}
    # ponytail: only simple annotations are checked (bool/int/str). Optional/Union are
    # skipped and left to the function itself. Enough to stop the LLM passing the
    # string "có" into a bool field, which would silently read as truthy.
    hints = typing.get_type_hints(fn)
    for k, v in args.items():
        t = hints.get(k)
        if t in (bool, int, str) and not isinstance(v, t):
            return {"status": "error", "message": f"Tham số '{k}' phải kiểu {t.__name__}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"status": "error", "message": f"Gọi {name} lỗi: {e}"}

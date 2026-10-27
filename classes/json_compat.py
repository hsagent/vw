"""Совместимый JSON-бэкенд: orjson при наличии, стандартный json иначе."""

try:
    import orjson as _json
except ImportError:
    import json as _json

    JSONDecodeError = _json.JSONDecodeError
    OPT_INDENT_2 = 1

    def loads(data):
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        return _json.loads(data)

    def dumps(value, option=0):
        indent = 2 if option & OPT_INDENT_2 else None
        return _json.dumps(
            value,
            ensure_ascii=False,
            indent=indent,
            separators=None if indent else (",", ":"),
        ).encode("utf-8")
else:
    JSONDecodeError = _json.JSONDecodeError
    OPT_INDENT_2 = _json.OPT_INDENT_2
    loads = _json.loads
    dumps = _json.dumps

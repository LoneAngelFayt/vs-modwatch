import re
from packaging.version import Version


def _normalize(v: str) -> Version:
    parts = v.strip().split(".")
    while len(parts) < 3:
        parts.append("0")
    return Version(".".join(parts))


def is_compatible(vs_version_str: str, target: str) -> bool:
    s = vs_version_str.strip()

    m = re.match(r"^>=\s*(\d+\.\d+(?:\.\d+)?)$", s)
    if m:
        return _normalize(target) >= _normalize(m.group(1))

    m = re.match(r"^(\d+\.\d+(?:\.\d+)?)\s*-\s*(\d+\.\d+(?:\.\d+)?)$", s)
    if m:
        return _normalize(m.group(1)) <= _normalize(target) <= _normalize(m.group(2))

    return _normalize(target) == _normalize(s)


def parse_vs_versions(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for v in raw:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    result.sort(key=lambda v: _normalize(v), reverse=True)
    return result

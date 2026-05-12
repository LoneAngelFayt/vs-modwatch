import re
from packaging.version import Version


def _normalize(v: str) -> Version:
    parts = v.strip().split(".")
    while len(parts) < 3:
        parts.append("0")
    return Version(".".join(parts))


def is_compatible(vs_version_str: str, target: str) -> bool:
    if not vs_version_str or not vs_version_str.strip():
        return False
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


def compat_level(vs_version_str: str, target: str) -> str:
    """Return 'compatible', 'warn', or 'stale' for a mod vs a target VS version.

    warn  = exact single version, patch only differs (likely still works)
    stale = exact single version, minor or major differs (probably broken)
    Explicit >= and range expressions are evaluated strictly — compatible or stale, no warn path.
    """
    if not vs_version_str or not vs_version_str.strip():
        return "stale"

    s = vs_version_str.strip()

    # >= expression — strictly compatible or stale
    m = re.match(r"^>=\s*(\d+\.\d+(?:\.\d+)?)$", s)
    if m:
        return "compatible" if _normalize(target) >= _normalize(m.group(1)) else "stale"

    # Range expression — strictly compatible or stale
    m = re.match(r"^(\d+\.\d+(?:\.\d+)?)\s*-\s*(\d+\.\d+(?:\.\d+)?)$", s)
    if m:
        in_range = _normalize(m.group(1)) <= _normalize(target) <= _normalize(m.group(2))
        return "compatible" if in_range else "stale"

    # Exact single version
    try:
        mod_v = _normalize(s)
        tgt_v = _normalize(target)
    except Exception:
        return "stale"

    if mod_v == tgt_v:
        return "compatible"
    if mod_v.major == tgt_v.major and mod_v.minor == tgt_v.minor:
        return "warn"
    return "stale"

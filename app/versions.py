import re
from packaging.version import Version


def _normalize(v: str) -> Version:
    """Normalize a VS version string to a PEP 440 Version.

    Handles VS-specific pre-release formats:
      '1.22.0-rc.5'  -> Version('1.22.0rc5')   (release candidate, sortable)
      '1.22.0-pre.1' -> Version('1.22.0')       (treat as stable for range checks)
    """
    v = v.strip()
    v = re.sub(r"-rc\.(\d+)$", r"rc\1", v, flags=re.IGNORECASE)
    v = re.sub(r"-pre\.\d+$", "", v, flags=re.IGNORECASE)
    parts = v.split(".")
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

    m = re.match(r"^(\d+\.\d+(?:\.\d+)?(?:-\S+)?)\s+-\s+(\d+\.\d+(?:\.\d+)?(?:-\S+)?)$", s)
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

    warn  = patch only differs from the relevant version boundary (likely still works)
    stale = minor or major differs (probably broken)
    For ranges, warn is returned when the target is one patch above the upper bound.
    >= expressions are strictly compatible or stale.
    """
    if not vs_version_str or not vs_version_str.strip():
        return "stale"

    s = vs_version_str.strip()

    # >= expression — strictly compatible or stale
    m = re.match(r"^>=\s*(\d+\.\d+(?:\.\d+)?)$", s)
    if m:
        return "compatible" if _normalize(target) >= _normalize(m.group(1)) else "stale"

    # Range expression
    m = re.match(r"^(\d+\.\d+(?:\.\d+)?(?:-\S+)?)\s+-\s+(\d+\.\d+(?:\.\d+)?(?:-\S+)?)$", s)
    if m:
        lo = _normalize(m.group(1))
        hi = _normalize(m.group(2))
        tgt = _normalize(target)
        if lo <= tgt <= hi:
            return "compatible"
        # Target is only a patch version above the upper bound — may still work
        if tgt > hi and tgt.major == hi.major and tgt.minor == hi.minor:
            return "warn"
        return "stale"

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

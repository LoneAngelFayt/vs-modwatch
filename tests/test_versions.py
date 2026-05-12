from app.versions import is_compatible, parse_vs_versions, compat_level

def test_gte_exact():
    assert is_compatible(">=1.19", "1.19.0") is True

def test_gte_above():
    assert is_compatible(">=1.19", "1.21.6") is True

def test_gte_below():
    assert is_compatible(">=1.19", "1.18.15") is False

def test_range_in():
    assert is_compatible("1.21.0 - 1.21.5", "1.21.3") is True

def test_range_lower_boundary():
    assert is_compatible("1.21.0 - 1.21.5", "1.21.0") is True

def test_range_upper_boundary():
    assert is_compatible("1.21.0 - 1.21.5", "1.21.5") is True

def test_range_above():
    assert is_compatible("1.21.0 - 1.21.5", "1.21.6") is False

def test_range_below():
    assert is_compatible("1.21.0 - 1.21.5", "1.20.15") is False

def test_exact_match():
    assert is_compatible("1.21.6", "1.21.6") is True

def test_exact_no_match():
    assert is_compatible("1.21.6", "1.21.5") is False

def test_two_part_gte():
    assert is_compatible(">=1.19", "1.19.3") is True

def test_parse_vs_versions_sorted_desc():
    result = parse_vs_versions(["1.19.8", "1.21.6", "1.21.5"])
    assert result[0] == "1.21.6"

def test_parse_vs_versions_deduplicates():
    result = parse_vs_versions(["1.21.6", "1.21.6", "1.19.0"])
    assert len(result) == 2

def test_empty_vs_version_returns_false():
    assert is_compatible("", "1.21.6") is False

def test_whitespace_vs_version_returns_false():
    assert is_compatible("   ", "1.21.6") is False


def test_compat_level_compatible_gte():
    assert compat_level(">=1.19", "1.21.6") == "compatible"

def test_compat_level_compatible_range():
    assert compat_level("1.19.0 - 1.21.6", "1.21.6") == "compatible"

def test_compat_level_warn_patch_differs():
    assert compat_level("1.21.3", "1.21.6") == "warn"

def test_compat_level_warn_patch_below():
    assert compat_level("1.21.0", "1.21.6") == "warn"

def test_compat_level_stale_minor_differs():
    assert compat_level("1.19.8", "1.21.6") == "stale"

def test_compat_level_stale_major_differs():
    assert compat_level("1.18.15", "1.21.6") == "stale"

def test_compat_level_empty_string():
    assert compat_level("", "1.21.6") == "stale"

def test_compat_level_exact_match():
    assert compat_level("1.21.6", "1.21.6") == "compatible"

def test_compat_level_gte_below_is_stale():
    assert compat_level(">=1.19", "1.18.0") == "stale"

# Pre-release version handling (e.g. "1.22.0-pre.1 - 1.22.2")
def test_compat_level_range_with_prerelease_lo_in():
    assert compat_level("1.22.0-pre.1 - 1.22.2", "1.22.1") == "compatible"

def test_compat_level_range_with_prerelease_lo_boundary():
    assert compat_level("1.22.0-pre.1 - 1.22.2", "1.22.0") == "compatible"

def test_compat_level_range_with_prerelease_hi_boundary():
    assert compat_level("1.22.0-pre.1 - 1.22.2", "1.22.2") == "compatible"

def test_compat_level_range_with_prerelease_above():
    assert compat_level("1.22.0-pre.1 - 1.22.2", "1.22.3") == "stale"

def test_compat_level_range_with_prerelease_below():
    assert compat_level("1.22.0-pre.1 - 1.22.2", "1.21.6") == "stale"

def test_is_compatible_range_with_prerelease():
    assert is_compatible("1.22.0-pre.1 - 1.22.2", "1.22.1") is True

def test_parse_vs_versions_skips_prerelease_gracefully():
    # Pre-release versions sort correctly after stripping suffix
    result = parse_vs_versions(["1.22.2", "1.22.0-pre.1", "1.21.6"])
    assert result[0] == "1.22.2"

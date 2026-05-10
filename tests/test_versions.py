from app.versions import is_compatible, parse_vs_versions

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

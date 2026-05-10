import pytest
from pathlib import Path
from app.scraper import parse_mod_page, parse_vs_version_list, ModPageData

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def mod_html():
    return (FIXTURES / "mod_page.html").read_text()

@pytest.fixture
def vs_html():
    return (FIXTURES / "vs_versions_page.html").read_text()

def test_parse_name(mod_html):
    data = parse_mod_page(mod_html)
    assert data.name == "Purposeful Storage"

def test_parse_current_version(mod_html):
    data = parse_mod_page(mod_html)
    assert data.current_version == "v1.3.2"

def test_parse_vs_version(mod_html):
    data = parse_mod_page(mod_html)
    assert data.vs_version == ">=1.19"

def test_parse_side_both(mod_html):
    data = parse_mod_page(mod_html)
    assert data.side == "both"

def test_parse_history_count(mod_html):
    data = parse_mod_page(mod_html)
    assert len(data.version_history) == 2

def test_parse_history_entry(mod_html):
    data = parse_mod_page(mod_html)
    assert data.version_history[0]["version"] == "v1.3.2"
    assert data.version_history[0]["vs_version"] == ">=1.19"

def test_parse_last_updated_not_none(mod_html):
    data = parse_mod_page(mod_html)
    assert data.last_updated is not None

def test_parse_vs_version_list_returns_list(vs_html):
    versions = parse_vs_version_list(vs_html)
    assert isinstance(versions, list)
    assert len(versions) > 0

def test_parse_vs_version_list_sorted_desc(vs_html):
    from packaging.version import Version
    versions = parse_vs_version_list(vs_html)
    parsed = [Version(v) for v in versions]
    assert parsed == sorted(parsed, reverse=True)

def test_parse_vs_version_list_contains_known(vs_html):
    assert "1.21.6" in parse_vs_version_list(vs_html)

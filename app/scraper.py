import re
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from app.versions import parse_vs_versions


@dataclass
class ModPageData:
    name: str
    current_version: str
    vs_version: str
    side: str  # "client", "server", "both"
    last_updated: Optional[datetime]
    version_history: list[dict]  # [{"version": str, "vs_version": str, "released_at": datetime|None}]


def _parse_side(raw: str) -> str:
    raw = raw.lower()
    if "client and server" in raw or "both" in raw:
        return "both"
    if "server" in raw:
        return "server"
    return "client"


def _strip_ordinal(s: str) -> str:
    """Remove ordinal suffixes: '9th' -> '9', '1st' -> '1', etc."""
    return re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s)


def _parse_date(raw: str) -> Optional[datetime]:
    """
    Parse date strings from mods.vintagestory.at.
    Live format: "Nov 9th 2025 at 12:02 PM"
    Also handles plain formats for fixture flexibility.
    """
    raw = raw.strip()
    # Strip the time portion " at HH:MM AM/PM" if present
    raw_date = re.sub(r"\s+at\s+\d+:\d+\s*(?:AM|PM)", "", raw, flags=re.IGNORECASE).strip()
    # Strip ordinal suffixes from day numbers
    raw_date = _strip_ordinal(raw_date)
    for fmt in ("%b %d %Y", "%B %d %Y", "%Y-%m-%d", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw_date, fmt)
        except ValueError:
            continue
    return None


def _parse_file_size(raw: str) -> int | None:
    """Convert '1.8 MB' / '512 KB' / '2.1 GB' to bytes, return None if unparseable."""
    import re as _re
    m = _re.match(r"([\d.]+)\s*(KB|MB|GB)", raw.strip(), _re.IGNORECASE)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).upper()
    return int(value * {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit])


def _parse_game_versions(td) -> str:
    """Extract game version string from a release row's game-version cell.

    When multiple tags are present, only the first is used — joined strings
    like '1.21.5 and 1.21.6' cannot be parsed by app.versions.is_compatible().
    """
    tags = td.select(".tags .tag")
    return tags[0].get_text(strip=True) if tags else ""


def parse_mod_page(html: str) -> ModPageData:
    """Parse a mod page HTML string into ModPageData."""
    soup = BeautifulSoup(html, "html.parser")

    # Mod name: inside .edit-asset h2, last <span>
    name = ""
    h2 = soup.select_one(".edit-asset h2")
    if h2:
        spans = h2.find_all("span")
        if spans:
            name = spans[-1].get_text(strip=True)

    # Side: in dl.infobox, find <dt>Side:</dt> then the immediately following <dt>
    side = "both"
    infobox = soup.select_one("dl.infobox")
    if infobox:
        for dt in infobox.find_all("dt"):
            if dt.get_text(strip=True).lower() == "side:":
                next_dt = dt.find_next_sibling("dt")
                if next_dt:
                    side = _parse_side(next_dt.get_text(strip=True))
                break

    # Release rows: table.release-table tbody tr[data-assetid]
    release_rows = soup.select("table.release-table tbody tr[data-assetid]")
    version_history = []
    for row in release_rows:
        tds = row.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
        version = tds[0].get_text(strip=True)
        vs_version = _parse_game_versions(tds[2])
        date_span = tds[4].find("span")
        date_text = date_span.get_text(strip=True) if date_span else tds[4].get_text(strip=True)

        # Download info: td[6] contains <a class="mod-dl" href="/download/...">filename.zip</a>
        download_url = None
        filename = None
        file_size = None
        if len(tds) > 6:
            dl_link = tds[6].find("a", class_="mod-dl")
            if dl_link:
                href = dl_link.get("href", "")
                if href.startswith("/"):
                    download_url = "https://mods.vintagestory.at" + href
                elif href:
                    download_url = href
                link_text = dl_link.get_text(strip=True)
                filename = link_text if link_text.endswith(".zip") else href.rsplit("/", 1)[-1]
            # File size: not present on the live page; set to None
            file_size_el = tds[6].find(class_="filesize") if len(tds) > 6 else None
            if file_size_el:
                file_size = _parse_file_size(file_size_el.get_text(strip=True))

        version_history.append({
            "version": version,
            "vs_version": vs_version,
            "released_at": _parse_date(date_text),
            "download_url": download_url,
            "filename": filename,
            "file_size": file_size,
        })

    current = version_history[0] if version_history else {}
    return ModPageData(
        name=name,
        current_version=current.get("version", ""),
        vs_version=current.get("vs_version", ""),
        side=side,
        last_updated=current.get("released_at"),
        version_history=version_history,
    )


def parse_vs_version_list(html: str) -> list[str]:
    """Parse VS game versions from mod portal filter HTML."""
    soup = BeautifulSoup(html, "html.parser")
    # Real selector: select[name="gv[]"] option with a non-empty value
    options = soup.select('select[name="gv[]"] option')
    raw = [opt.get("value", "").strip() for opt in options if opt.get("value", "").strip()]
    return parse_vs_versions(raw)


async def fetch_mod_page(url: str) -> ModPageData:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return parse_mod_page(resp.text)


async def fetch_vs_versions() -> list[str]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get("https://mods.vintagestory.at/list/mod")
        resp.raise_for_status()
    return parse_vs_version_list(resp.text)

"""Collects upcoming events at the SEC (Glasgow) and saves them to events.json.

Step 1 of the Glasgow events project. Later steps will add Hampden,
Celtic Park and Ibrox, then notifications.
"""

import json
import re
import sys
from datetime import date, datetime
from urllib.parse import urljoin, urldefrag
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

PAGES = ["https://www.sec.co.uk/events", "https://www.sec.co.uk/"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal Glasgow events project; checks once a day)"
}
VENUES = ["OVO Hydro", "SEC Armadillo", "SEC Centre", "Lomond Auditorium"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]

# Matches dates like "26 Oct 2026", "27 Oct - 26 Nov 2026" and "20 - 21 Feb 2027".
DATE_RE = re.compile(
    r"(?P<d1>\d{1,2})\s*(?P<m1>[A-Za-z]{3,9})?\s*-\s*(?P<d2>\d{1,2})\s+"
    r"(?P<m2>[A-Za-z]{3,9})\s+(?P<y>\d{4})"
    r"|(?P<d>\d{1,2})\s+(?P<m>[A-Za-z]{3,9})\s+(?P<y2>\d{4})"
)


def to_date(day, month_name, year):
    """Turn day / month name / year text into a date, or None if it isn't one."""
    prefix = (month_name or "")[:3].lower()
    if prefix not in MONTHS:
        return None
    try:
        return date(int(year), MONTHS.index(prefix) + 1, int(day))
    except ValueError:
        return None


def parse_dates(text):
    """Return a list of (start_date, end_date) found in a block of text."""
    found = []
    for m in DATE_RE.finditer(text):
        if m.group("d2"):  # a range
            end = to_date(m.group("d2"), m.group("m2"), m.group("y"))
            start = to_date(m.group("d1"), m.group("m1") or m.group("m2"), m.group("y"))
            if start and end and start > end:  # range that crosses New Year
                start = start.replace(year=start.year - 1)
        else:  # a single day
            start = end = to_date(m.group("d"), m.group("m"), m.group("y2"))
        if start and end:
            found.append((start, end))
    return found


def normalise(href, base):
    return urldefrag(urljoin(base, href))[0]


def is_event_link(href):
    return "/events/detail/" in href


def find_card(anchor, base):
    """Walk up from an event link to the smallest block that holds its date."""
    node = anchor.parent
    for _ in range(8):
        if node is None:
            return None
        urls = {normalise(a["href"], base)
                for a in node.find_all("a", href=True) if is_event_link(a["href"])}
        if len(urls) > 1:  # gone too far: this block holds several events
            return None
        if DATE_RE.search(node.get_text(" ", strip=True)):
            return node
        node = node.parent
    return None


def parse_page(html, base):
    """Return a list of event dicts found in one page of HTML."""
    soup = BeautifulSoup(html, "html.parser")
    anchors = {}
    for a in soup.find_all("a", href=True):
        if is_event_link(a["href"]):
            anchors.setdefault(normalise(a["href"], base), []).append(a)

    events = []
    for url, links in anchors.items():
        card = None
        for link in links:
            card = find_card(link, base)
            if card:
                break
        if card is None:
            continue

        text = " ".join(card.get_text(" ", strip=True).split())
        heading = card.find(["h2", "h3", "h4", "h5"])
        title = heading.get_text(" ", strip=True) if heading else ""
        if not title:
            title = max((l.get_text(" ", strip=True) for l in links), key=len, default="")
        if not title:
            title = url.rstrip("/").split("/")[-1].replace("-", " ").title()

        venue = next((v for v in VENUES if v.lower() in text.lower()), "SEC")

        for start, end in parse_dates(text):
            events.append({
                "title": title,
                "venue": venue,
                "area": "SEC",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "time": None,
                "url": url,
            })
    return events


def main():
    today = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    events = {}
    last_text = ""

    for page in PAGES:
        try:
            response = requests.get(page, headers=HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException as err:
            print(f"Could not load {page}: {err}")
            continue
        last_text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        found = parse_page(response.text, page)
        print(f"{page}: found {len(found)} event dates")
        for e in found:
            events[(e["url"], e["start"])] = e

    if not events:
        print("\nNo events found. The SEC page probably looks different from what")
        print("this script expects. Copy everything below and send it to Claude:\n")
        print(last_text[:1500] or "(the page came back empty)")
        sys.exit(1)

    upcoming = sorted(
        (e for e in events.values() if e["end"] >= today),
        key=lambda e: (e["start"], e["title"]),
    )
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(upcoming, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(upcoming)} upcoming SEC events to events.json. First few:")
    for e in upcoming[:10]:
        print(f"  {e['start']}  {e['title']}  ({e['venue']})")


if __name__ == "__main__":
    main()

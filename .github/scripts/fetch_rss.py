#!/usr/bin/env python3
"""Holt den Presseportal-RSS-Feed (Polizei NRW) und schreibt rss/feed.json.

Läuft per GitHub Action. Der Browser darf den Feed wegen fehlender
CORS-Freigabe nicht direkt laden, deshalb liegt die JSON-Kopie neben dem
Widget auf GitHub Pages.

Die Datei wird nur neu geschrieben, wenn sich die Meldungen geändert haben
oder der letzte Stand älter als HEARTBEAT ist. So entstehen keine unnötigen
Commits, und das Widget erkennt trotzdem, ob die Aktualisierung noch läuft.
"""
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FEED_URL = "https://www.presseportal.de/rss/polizei/laender/9.rss2"
OUT = Path(__file__).resolve().parents[2] / "rss" / "feed.json"
MAX_ITEMS = 30
HEARTBEAT = timedelta(minutes=60)
USER_AGENT = "Mozilla/5.0 (compatible; rss-kachel/1.0)"

# "POL-EU: Titel"  ->  Kürzel + Titel
PREFIX_RE = re.compile(r"^([A-ZÄÖÜ][A-ZÄÖÜ0-9]*(?:-[A-ZÄÖÜ0-9]+)+):\s*(.+)$")
# angehängte Vorgangsnummer "… - 2611077"
TRAIL_ID_RE = re.compile(r"\s+-\s+\d{5,}$")
# "Ort (ots) - Text"  ->  Ort + Text
OTS_RE = re.compile(r"^(.{1,80}?)\s*\(ots\)\s*[-–]\s*(.*)$", re.S)
# interne Laufnummer am Textanfang "Lfd. Nr.: 0973"
LFD_NR_RE = re.compile(r"^Lfd\.\s*Nr\.?:?\s*\d+\s*")


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fetch():
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(FEED_URL, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as exc:  # Netzwerkfehler: kurz warten, erneut versuchen
            last_error = exc
            time.sleep(5 * (attempt + 1))
    raise last_error


def iso_utc(value):
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def parse(raw):
    channel = ET.fromstring(raw).find("channel")
    if channel is None:
        raise ValueError("Kein <channel> im Feed")
    items = []
    for node in channel.findall("item")[:MAX_ITEMS]:
        title, prefix = clean(node.findtext("title")), ""
        match = PREFIX_RE.match(title)
        if match:
            prefix, title = match.group(1), match.group(2)
        title = TRAIL_ID_RE.sub("", title)

        teaser, place = clean(node.findtext("description")), ""
        match = OTS_RE.match(teaser)
        if match:
            place, teaser = clean(match.group(1)), clean(match.group(2))
        teaser = LFD_NR_RE.sub("", teaser)
        if teaser.endswith("..."):
            teaser = teaser[:-3].rstrip() + " …"

        items.append({
            "title": title,
            "prefix": prefix,
            "place": place,
            "teaser": teaser,
            "source": clean(node.findtext("source")),
            "published": iso_utc(node.findtext("pubDate")),
            "link": clean(node.findtext("link")),
        })
    return items


def main():
    try:
        items = parse(fetch())
    except Exception as exc:
        # Kein Fehlschlag des Jobs: das Widget zeigt den alten Stand mit Status an.
        print(f"::warning::Feed konnte nicht geladen werden: {exc}")
        return 0
    if not items:
        print("::warning::Feed enthielt keine Meldungen – alter Stand bleibt.")
        return 0

    now = datetime.now(timezone.utc)
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None

    if old and old.get("items") == items:
        try:
            checked = datetime.fromisoformat(old["checked"].replace("Z", "+00:00"))
            if now - checked < HEARTBEAT:
                print("Meldungen unverändert – keine Aktualisierung nötig.")
                return 0
        except (KeyError, ValueError):
            pass

    data = {
        "source": "presseportal.de / news aktuell",
        "feed": FEED_URL,
        "checked": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(items)} Meldungen geschrieben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

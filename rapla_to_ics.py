#!/usr/bin/env python3
"""
Rapla DHBW -> ICS Konverter

Lädt deinen DHBW-Rapla-Stundenplan und erzeugt eine .ics-Datei,
die du in Google Calendar / Apple Calendar / Outlook importieren kannst.

Benutzung:
    python rapla_to_ics.py "<RAPLA_URL>" --start 2025-09-01 --end 2026-09-30 -o stundenplan.ics

Abhängigkeiten:
    pip install requests beautifulsoup4 icalendar
"""

import argparse
import re
import sys
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event


def build_week_url(base_url: str, target: date) -> str:
    """Setzt day/month/year-Parameter, damit Rapla die richtige Woche ausliefert."""
    parsed = urlparse(base_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["day"] = [str(target.day)]
    params["month"] = [str(target.month)]
    params["year"] = [str(target.year)]
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def parse_date_from_th(text: str, fallback_year: int) -> date | None:
    """Extrahiert ein Datum wie 'Mo 15.09.' oder '15.09.25' aus dem Tabellenkopf."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?", text)
    if not m:
        return None
    day, month, year = m.group(1), m.group(2), m.group(3)
    if not year:
        year = fallback_year
    year = int(year)
    if year < 100:
        year += 2000
    try:
        return date(year, int(month), int(day))
    except ValueError:
        return None


def parse_time_range(text: str):
    """Sucht 'HH:MM-HH:MM' im Text und gibt (start, end) als time-Objekte zurück."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    sh, sm, eh, em = map(int, m.groups())
    return (sh, sm, eh, em)


def parse_week(html: str, week_anchor: date) -> list[dict]:
    """Parst eine Rapla-Wochenseite und liefert eine Liste von Terminen."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict] = []

    # Die Wochenansicht ist eine Tabelle mit Spalten pro Tag.
    # Wir suchen das Datum in den Spaltenüberschriften (<th>).
    week_table = soup.find("table", class_=re.compile("week_table|calendar"))
    if not week_table:
        return events

    # Spalten-Index -> Datum
    headers = week_table.find_all("th")
    col_dates: dict[int, date] = {}
    for idx, th in enumerate(headers):
        d = parse_date_from_th(th.get_text(" ", strip=True), week_anchor.year)
        if d:
            col_dates[idx] = d

    # Termin-Blöcke
    for block in week_table.find_all("td", class_=re.compile("week_block")):
        # Spalte des Blocks bestimmen
        row = block.find_parent("tr")
        if not row:
            continue
        col_idx = list(row.find_all("td")).index(block)
        # Kopfspalte (uhrzeit links) abziehen falls vorhanden
        # Wir matchen lieber gegen das nächstgelegene Datum
        if col_idx in col_dates:
            day = col_dates[col_idx]
        else:
            # Fallback: erste Spalte ist meist Zeit -> col_idx-1
            day = col_dates.get(col_idx - 1)
        if not day:
            continue

        text = block.get_text("\n", strip=True)
        tr = parse_time_range(text)
        if not tr:
            continue
        sh, sm, eh, em = tr

        # Tooltip enthält oft strukturierte Infos
        tooltip = block.find("span", class_="tooltip")
        title = ""
        location = ""
        description_parts: list[str] = []

        if tooltip:
            strong = tooltip.find("strong")
            if strong:
                title = strong.get_text(" ", strip=True)
            # Tabelle im Tooltip mit Schlüssel/Wert
            for row in tooltip.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 2:
                    key, value = cells[0].rstrip(":"), cells[1]
                    description_parts.append(f"{key}: {value}")
                    if "ressource" in key.lower() or "raum" in key.lower():
                        location = value
                    if not title and ("titel" in key.lower() or "veranstaltung" in key.lower()):
                        title = value

        # Fallback: Titel aus dem sichtbaren Text ziehen (alles außer Uhrzeit)
        if not title:
            visible = re.sub(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", "", text).strip()
            title = visible.split("\n")[0] if visible else "Termin"

        # Räume/Personen aus den sichtbaren <span class="resource"> / "person"
        resources = [s.get_text(" ", strip=True) for s in block.find_all("span", class_="resource")]
        persons = [s.get_text(" ", strip=True) for s in block.find_all("span", class_="person")]
        if resources and not location:
            location = ", ".join(resources)
        if persons:
            description_parts.append("Personen: " + ", ".join(persons))

        events.append({
            "title": title,
            "start": datetime(day.year, day.month, day.day, sh, sm),
            "end": datetime(day.year, day.month, day.day, eh, em),
            "location": location,
            "description": "\n".join(description_parts),
        })

    return events


def filter_events(events: list[dict], excludes: list[str], includes: list[str]) -> list[dict]:
    """Filtert Termine nach Stichwörtern (case-insensitive Substring-Match auf Titel+Beschreibung)."""
    excludes_lc = [x.lower() for x in excludes if x.strip()]
    includes_lc = [x.lower() for x in includes if x.strip()]
    result = []
    for e in events:
        haystack = (e["title"] + " " + e.get("description", "")).lower()
        if any(x in haystack for x in excludes_lc):
            continue
        if includes_lc and not any(x in haystack for x in includes_lc):
            continue
        result.append(e)
    return result


def load_patterns(path: str | None) -> list[str]:
    """Lädt Patterns aus einer Datei (eine pro Zeile, # = Kommentar)."""
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]
    except FileNotFoundError:
        return []


def dedupe(events: list[dict]) -> list[dict]:
    """Entfernt Duplikate (gleicher Titel + Start + Ende)."""
    seen = set()
    unique = []
    for e in events:
        key = (e["title"], e["start"], e["end"], e["location"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def build_ics(events: list[dict]) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Rapla DHBW to ICS//DE")
    cal.add("version", "2.0")
    for e in events:
        ev = Event()
        ev.add("summary", e["title"])
        ev.add("dtstart", e["start"])
        ev.add("dtend", e["end"])
        if e["location"]:
            ev.add("location", e["location"])
        if e["description"]:
            ev.add("description", e["description"])
        ev.add("uid", str(uuid.uuid4()) + "@rapla-dhbw")
        ev.add("dtstamp", datetime.utcnow())
        cal.add_component(ev)
    return cal.to_ical()


def iterate_weeks(start: date, end: date):
    """Liefert Montagsdaten von start bis end."""
    monday = start - timedelta(days=start.weekday())
    while monday <= end:
        yield monday
        monday += timedelta(days=7)


def main():
    parser = argparse.ArgumentParser(description="Rapla DHBW -> ICS")
    parser.add_argument("url", help="Deine Rapla-URL (in Anführungszeichen)")
    parser.add_argument("--start", default=None, help="Startdatum YYYY-MM-DD (Default: heute)")
    parser.add_argument("--end", default=None, help="Enddatum YYYY-MM-DD (Default: heute + 1 Jahr)")
    parser.add_argument("-o", "--output", default="stundenplan.ics", help="Ausgabedatei")
    parser.add_argument("--exclude", action="append", default=[],
                        help="Stichwort, das ausgeschlossen wird (mehrfach verwendbar)")
    parser.add_argument("--include", action="append", default=[],
                        help="Nur Termine mit diesem Stichwort (mehrfach verwendbar)")
    parser.add_argument("--exclude-file", help="Datei mit Ausschluss-Stichwörtern (eine pro Zeile)")
    parser.add_argument("--include-file", help="Datei mit Einschluss-Stichwörtern (eine pro Zeile)")
    args = parser.parse_args()

    excludes = args.exclude + load_patterns(args.exclude_file)
    includes = args.include + load_patterns(args.include_file)

    today = date.today()
    start = date.fromisoformat(args.start) if args.start else today
    end = date.fromisoformat(args.end) if args.end else today + timedelta(days=365)

    print(f"Lade Stundenplan von {start} bis {end} ...", file=sys.stderr)
    all_events: list[dict] = []
    session = requests.Session()
    session.headers.update({"User-Agent": "rapla-to-ics/1.0"})

    weeks = list(iterate_weeks(start, end))
    for i, monday in enumerate(weeks, 1):
        url = build_week_url(args.url, monday)
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
        except requests.RequestException as exc:
            print(f"  Woche {monday}: Fehler ({exc})", file=sys.stderr)
            continue
        evs = parse_week(r.text, monday)
        all_events.extend(evs)
        print(f"  [{i}/{len(weeks)}] {monday}: {len(evs)} Termine", file=sys.stderr)

    all_events = dedupe(all_events)
    # Auf Datumsbereich filtern
    all_events = [e for e in all_events if start <= e["start"].date() <= end]

    before = len(all_events)
    all_events = filter_events(all_events, excludes, includes)
    if excludes or includes:
        print(f"Filter: {before} -> {len(all_events)} Termine "
              f"(ausgeschlossen: {excludes or '-'}; nur: {includes or '-'})", file=sys.stderr)

    ics = build_ics(all_events)
    with open(args.output, "wb") as f:
        f.write(ics)
    print(f"\nFertig: {len(all_events)} Termine -> {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

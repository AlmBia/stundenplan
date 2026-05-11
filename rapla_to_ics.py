#!/usr/bin/env python3
"""
Rapla DHBW -> ICS Konverter

Lädt deinen DHBW-Rapla-Stundenplan und erzeugt eine .ics-Datei.
Die Year-View von Rapla zeigt 52 Wochen ab dem angegebenen Datum,
also reicht 1 HTTP-Request pro Jahr.

Benutzung:
    python rapla_to_ics.py "<RAPLA_URL>" -o stundenplan.ics
    python rapla_to_ics.py "<URL>" --exclude "Sport" --exclude "Französisch"
    python rapla_to_ics.py "<URL>" --exclude-file exclude.txt

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


def build_url(base_url: str, anchor: date) -> str:
    """Setzt day/month/year, damit Rapla ab diesem Datum 52 Wochen liefert."""
    parsed = urlparse(base_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["day"] = [str(anchor.day)]
    params["month"] = [str(anchor.month)]
    params["year"] = [str(anchor.year)]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def parse_block(cell, event_date: date) -> dict | None:
    """Extrahiert Daten aus einer <td class='week_block'>-Zelle."""
    a = cell.find("a")
    text_source = a if a else cell
    raw_parts: list[str] = []
    for child in text_source.descendants:
        name = getattr(child, "name", None)
        if name == "br":
            raw_parts.append("\n")
        elif name is None:
            raw_parts.append(str(child))
    full_text = "".join(raw_parts).replace("\xa0", " ")
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    m = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", full_text)
    if not m:
        return None
    sh, sm, eh, em = map(int, m.groups())

    span_texts = {s.get_text(" ", strip=True) for s in cell.find_all("span")}
    title = ""
    for line in lines:
        cleaned = re.sub(r"\d{1,2}:\d{2}\s*-?\s*\d{1,2}:\d{2}", "", line).strip()
        if cleaned and not re.fullmatch(r"[\s\-:]+", cleaned) and cleaned not in span_texts:
            title = cleaned
            break
    if not title:
        title = "Termin"
    # Bereinigen: STG-Bezeichnungen raus, mehrfache Leerzeichen normalisieren
    title = re.sub(r"\bSTG-[A-Za-z0-9]+(\s*,\s*STG-[A-Za-z0-9]+)*", "", title)
    title = re.sub(r"\s+", " ", title).strip(" ,;-")

    persons = [s.get_text(" ", strip=True) for s in cell.find_all("span", class_="person")]
    resources = [s.get_text(" ", strip=True) for s in cell.find_all("span", class_="resource")]

    room = ""
    groups: list[str] = []
    for r in resources:
        if r.startswith("STG-"):
            groups.append(r)
        elif re.search(r"\d", r) and not room:
            room = r
        else:
            groups.append(r)

    description_lines = []
    if persons:
        description_lines.append("Dozent: " + ", ".join(persons))
    if groups:
        description_lines.append("Gruppe: " + ", ".join(groups))

    return {
        "title": title,
        "start": datetime(event_date.year, event_date.month, event_date.day, sh, sm),
        "end": datetime(event_date.year, event_date.month, event_date.day, eh, em),
        "location": room,
        "description": "\n".join(description_lines),
    }


def parse_table(table, current_year: int):
    """Parst eine week_table. Returns (events, week_no)."""
    first_row = table.find("tr")
    if not first_row:
        return [], None

    wn_cell = first_row.find(class_="week_number")
    week_no = None
    if wn_cell:
        m = re.search(r"\d+", wn_cell.get_text())
        if m:
            week_no = int(m.group())

    headers = first_row.find_all("td", class_="week_header")
    day_dates: dict[int, date] = {}
    col_to_day: dict[int, int] = {}
    months_seen: list[int] = []
    # Erste Spalte ist week_number (col 0), Tage starten bei col 1
    cur_col = 1
    for day_idx, hdr in enumerate(headers):
        try:
            hdr_cs = int(hdr.get("colspan", 1) or 1)
        except ValueError:
            hdr_cs = 1
        # Diese Spalten gehören zu diesem Tag
        for c in range(cur_col, cur_col + hdr_cs):
            col_to_day[c] = day_idx
        cur_col += hdr_cs

        txt = hdr.get_text(" ", strip=True)
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.", txt)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            months_seen.append(month)
            try:
                day_dates[day_idx] = date(current_year, month, day)
            except ValueError:
                pass

    # Jahreswechsel mitten in der Woche (Dez/Jan)
    if 12 in months_seen and 1 in months_seen:
        for idx, d in list(day_dates.items()):
            if d.month == 1:
                day_dates[idx] = date(current_year + 1, d.month, d.day)

    occupied: set[tuple[int, int]] = set()
    events: list[dict] = []

    for row_idx, tr in enumerate(table.find_all("tr")):
        col_idx = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while (row_idx, col_idx) in occupied:
                col_idx += 1
            try:
                rowspan = int(cell.get("rowspan", 1) or 1)
            except ValueError:
                rowspan = 1
            try:
                colspan = int(cell.get("colspan", 1) or 1)
            except ValueError:
                colspan = 1

            classes = cell.get("class") or []
            if "week_block" in classes:
                day_idx = col_to_day.get(col_idx, -1)
                event_date = day_dates.get(day_idx)
                if event_date:
                    parsed = parse_block(cell, event_date)
                    if parsed:
                        events.append(parsed)

            for r in range(row_idx, row_idx + rowspan):
                for c in range(col_idx, col_idx + colspan):
                    occupied.add((r, c))
            col_idx += colspan

    return events, week_no


def parse_html(html: str, anchor: date) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table", class_="week_table")

    all_events: list[dict] = []
    current_year = anchor.year
    last_week_no: int | None = None

    for table in tables:
        # Wochennummer-Drop erkennen -> Jahreswechsel
        first_row = table.find("tr")
        peek_week = None
        if first_row:
            wn = first_row.find(class_="week_number")
            if wn:
                m = re.search(r"\d+", wn.get_text())
                if m:
                    peek_week = int(m.group())
        if last_week_no is not None and peek_week is not None and peek_week < last_week_no - 5:
            current_year += 1

        evs, week_no = parse_table(table, current_year)
        last_week_no = week_no
        all_events.extend(evs)

    return all_events


def filter_events(events: list[dict], excludes: list[str], includes: list[str]) -> list[dict]:
    excludes_lc = [x.lower() for x in excludes if x.strip()]
    includes_lc = [x.lower() for x in includes if x.strip()]
    result = []
    for e in events:
        haystack = (e["title"] + " " + e.get("description", "") + " " + e.get("location", "")).lower()
        if any(x in haystack for x in excludes_lc):
            continue
        if includes_lc and not any(x in haystack for x in includes_lc):
            continue
        result.append(e)
    return result


def load_patterns(path: str | None) -> list[str]:
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    except FileNotFoundError:
        return []


def dedupe(events: list[dict]) -> list[dict]:
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
    cal.add("x-wr-calname", "DHBW Stundenplan")
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


def main():
    parser = argparse.ArgumentParser(description="Rapla DHBW -> ICS")
    parser.add_argument("url", help="Rapla-URL (in Anführungszeichen)")
    parser.add_argument("--anchor", default=None,
                        help="Ankerdatum YYYY-MM-DD (Default: heute - 4 Wochen)")
    parser.add_argument("-o", "--output", default="stundenplan.ics", help="Ausgabedatei")
    parser.add_argument("--exclude", action="append", default=[],
                        help="Ausschluss-Stichwort (mehrfach verwendbar)")
    parser.add_argument("--include", action="append", default=[],
                        help="Einschluss-Stichwort (mehrfach verwendbar)")
    parser.add_argument("--exclude-file", help="Datei mit Ausschluss-Stichwörtern")
    parser.add_argument("--include-file", help="Datei mit Einschluss-Stichwörtern")
    args = parser.parse_args()

    anchor = date.fromisoformat(args.anchor) if args.anchor else date.today() - timedelta(weeks=4)
    excludes = args.exclude + load_patterns(args.exclude_file)
    includes = args.include + load_patterns(args.include_file)

    url = build_url(args.url, anchor)
    print(f"Lade Rapla (Anker {anchor}) ...", file=sys.stderr)
    r = requests.get(url, timeout=60, headers={"User-Agent": "rapla-to-ics/2.0"})
    r.raise_for_status()

    events = parse_html(r.text, anchor)
    print(f"Geparst: {len(events)} Termine", file=sys.stderr)

    events = dedupe(events)
    before = len(events)
    events = filter_events(events, excludes, includes)
    if excludes or includes:
        print(f"Filter: {before} -> {len(events)} (ausgeschlossen: {excludes or '-'}; "
              f"nur: {includes or '-'})", file=sys.stderr)

    with open(args.output, "wb") as f:
        f.write(build_ics(events))
    print(f"Geschrieben: {args.output} ({len(events)} Termine)", file=sys.stderr)


if __name__ == "__main__":
    main()

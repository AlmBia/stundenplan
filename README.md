# stundenplan
6. Semester - Vorlesungsplan



# DHBW Stundenplan → Kalender (automatisch)

Lädt deinen Rapla-Stundenplan, filtert ungewollte Fächer raus und stellt
ihn als `.ics`-Datei bereit, die dein Kalender automatisch abonnieren kann.
GitHub Actions aktualisiert die Datei täglich von selbst.

## Inhalt der ZIP

- `rapla_to_ics.py` — das Skript (Rapla → ICS, mit Filter)
- `exclude.txt` — Stichwörter für Fächer, die ausgeschlossen werden sollen
- `.github/workflows/update.yml` — täglicher Auto-Update-Workflow

---

## Einrichtung (einmalig)

### 1. GitHub-Account
Falls noch nicht vorhanden: auf https://github.com kostenlos registrieren.

### 2. Repository erstellen
- Oben rechts **+** → **New repository**
- Name: z. B. `stundenplan`
- **Public** wählen
- Haken bei **Add a README file**
- **Create repository**

### 3. Dateien hochladen
Die Dateien aus dieser ZIP ins Repo laden. Wichtig — die Ordnerstruktur muss
erhalten bleiben:

```
stundenplan/
├── rapla_to_ics.py
├── exclude.txt
└── .github/
    └── workflows/
        └── update.yml
```

Am einfachsten:
- `rapla_to_ics.py` und `exclude.txt`: **Add file → Upload files** → reinziehen → **Commit changes**
- `update.yml`: **Add file → Create new file**, als Namen `.github/workflows/update.yml`
  eintragen (die Slashes erzeugen die Ordner automatisch), Inhalt aus der ZIP
  reinkopieren → **Commit changes**

### 4. Rapla-URL als Secret hinterlegen
- Repo → **Settings** → **Secrets and variables** → **Actions**
- **New repository secret**
- Name: `RAPLA_URL`
- Secret: deine komplette Rapla-URL
- **Add secret**

### 5. exclude.txt anpassen
`exclude.txt` im Repo öffnen → ✏️ → Stichwörter der Fächer eintragen, die NICHT
im Kalender erscheinen sollen (eine pro Zeile, Groß-/Kleinschreibung egal) →
**Commit changes**.

Tipp: erst leer lassen, einmal Schritt 6 laufen lassen, dann in `stundenplan.ics`
schauen welche Titel vorkommen und die passenden Stichwörter rauskopieren.

### 6. Workflow zum ersten Mal starten
- Repo → **Actions** → ggf. Workflows aktivieren bestätigen
- Links **Update Stundenplan** → **Run workflow** → **Run workflow**
- ~30–60 Sek warten, Seite neu laden → grüner Haken = erfolgreich

Danach liegt `stundenplan.ics` im Repo.

### 7. Kalender abonnieren
Abo-URL (Username ggf. anpassen):

```
https://raw.githubusercontent.com/AlmBia/stundenplan/main/stundenplan.ics
```

- **Apple Calendar (Mac):** Ablage → Neues Kalenderabonnement → URL einfügen →
  Aktualisierung z. B. „Jede Stunde“
- **iPhone/iPad:** Einstellungen → Apps → Kalender → Accounts → Account hinzufügen
  → Andere → Kalenderabo hinzufügen → URL einfügen
- **Google Calendar:** links bei „Weitere Kalender“ das **+** → Per URL → einfügen
- **Outlook:** Kalender hinzufügen → Aus dem Internet abonnieren

---

## Laufender Betrieb

- Der Workflow läuft **täglich automatisch** (ca. 5–6 Uhr deutscher Zeit) und
  committet eine neue `stundenplan.ics`, falls sich etwas geändert hat.
- Dein Kalender holt sich die neue Datei je nach eingestelltem Intervall.
- **Fach ausschließen/wieder reinnehmen:** `exclude.txt` bearbeiten, committen.
  Beim nächsten Lauf (oder manuell per *Run workflow*) wird gefiltert.

## Lokal testen (optional)

```bash
pip install requests beautifulsoup4 icalendar
python rapla_to_ics.py "DEINE_RAPLA_URL" --exclude-file exclude.txt -o stundenplan.ics
```

URL immer in Anführungszeichen setzen (wegen der `&`-Zeichen).

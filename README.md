# Duell-Bot für Discord

Ein Discord-Bot für 1v1-Duelle mit kleinem Einsatz, zum Beispiel 10 Cent pro Runde CS2.
Der Einsatz wird über **Lightning-Hold-Invoices** gesperrt. **Der Bot verwahrt zu keinem Zeitpunkt Geld.**
Er gibt nur am Ende dem Gewinner das Geheimnis (Preimage), mit dem dieser die Zahlung des Verlierers einlösen kann.

## Ablauf

1. `/duell herausfordern @gegner spiel einsatz`: Der Gegner klickt auf **Annehmen**.
2. Der Bot zeigt zwei Hashes:
   - **A** erstellt eine Hold-Invoice mit *Hash A*, B bezahlt sie.
   - **B** erstellt eine Hold-Invoice mit *Hash B*, A bezahlt sie.
   - Wer die Zahlung des anderen gesperrt erhalten hat, klickt auf **Zahlung erhalten**.
3. Das Spiel läuft. Danach melden beide `/duell ergebnis`.
   - Sind sich beide einig, steht das Ergebnis vorläufig fest.
   - Sind sie sich nicht einig, müssen **2 Schiedsrichter** (Rolle `Schiedsrichter`) übereinstimmen.
4. **Einspruchsfrist** (Standard: 10 Minuten): Ein Spieler kann **Einspruch** einlegen. Dann entscheiden die Schiedsrichter endgültig.
5. Danach holt sich der Gewinner mit `/duell geheimnis` sein Preimage (nur für ihn sichtbar) und löst die Invoice ein.
   Die andere Invoice wird nie eingelöst und läuft ab. Das Geld geht automatisch zurück.

Bei Unentschieden oder Abbruch gibt der Bot nichts frei, und beide Zahlungen gehen zurück.

| Befehl | Wer |
|---|---|
| `/duell herausfordern` | alle |
| `/duell ergebnis` | Spieler, Schiedsrichter |
| `/duell einspruch` | Spieler (während der Frist) |
| `/duell abbrechen` | Spieler vor Spielbeginn, Schiedsrichter jederzeit |
| `/duell info` | alle |
| `/duell geheimnis` | nur der Gewinner |

## Einrichtung

1. Im [Discord Developer Portal](https://discord.com/developers/applications) eine Anwendung anlegen, unter **Bot** einen Token erzeugen.
2. Unter *OAuth2 → URL Generator* die Scopes `bot` und `applications.commands` sowie die Berechtigung *Send Messages* wählen und den Bot einladen.
3. Auf dem Server eine Rolle `Schiedsrichter` anlegen.
4. Starten:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Token eintragen
set -a; source .env; set +a
python -m duellbot.bot
```

Tests: `pip install pytest && python -m pytest`

## Wichtige Grenzen

- **Hold-Invoices mit fremdem Hash:** Die Wallet muss Invoices mit einem vorgegebenen Payment-Hash erstellen und erst später einlösen können (bei LND z. B. `lncli addholdinvoice <hash> <betrag>` und `settleinvoice <preimage>`). Ob die Hydranet-Wallet das anbietet, ist noch zu prüfen.
- **Laufzeit:** Gesperrte Zahlungen binden Kapital im Lightning-Netz und laufen nach der Invoice-Ablaufzeit bzw. dem CLTV-Limit ab. Geeignet für Matches von Minuten bis wenigen Stunden.
- **Vertrauen:** Schiedsrichter können kein Geld behalten, aber falsch entscheiden. Deshalb sind mehrere Bestätigungen nötig.
- **Geheimnisse** liegen in der lokalen SQLite-Datei (`duelle.db`). Wer darauf Zugriff hat, kann Ergebnisse vorwegnehmen. Schütze den Server.
- **Recht:** Geldeinsätze auf Spiele mit Zufallsanteil (z. B. Poker) können in Deutschland als Glücksspiel gelten. Vor dem öffentlichen Einsatz rechtlich prüfen lassen.

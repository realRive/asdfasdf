# Duell-Bot für Discord

Ein Discord-Bot für 1v1-Duelle mit kleinem Einsatz, zum Beispiel 10 Cent pro Runde CS2.
Der Einsatz wird über **Lightning-Hold-Invoices** gesperrt. **Der Bot verwahrt zu keinem Zeitpunkt Geld.**
Er gibt nur am Ende dem Gewinner das Geheimnis (Preimage), mit dem dieser die Zahlung des Verlierers einlösen kann.

## Ablauf

1. `/duell herausfordern @gegner spiel einsatz_sat`: Der Einsatz wird in Satoshi angegeben, z. B. 150 sat ≈ 0,10 €. Der Gegner klickt auf **Annehmen**.
2. Der Bot zeigt zwei Hashes:
   - **A** erstellt eine Hold-Invoice mit *Hash A*, **B** eine mit *Hash B*.
   - Beide reichen sie mit `/duell invoice` ein. **Der Bot prüft Hash, Betrag, Netzwerk, Laufzeit und CLTV**
     und postet die Invoice erst danach als geprüft.
   - Jeder bezahlt **nur die vom Bot geprüfte Invoice** des anderen.
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
| `/duell invoice` | Spieler (vor Spielbeginn) |
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

## Invoice-Prüfung

Ohne Prüfung könnte ein Spieler eine Invoice mit dem Hash eines **eigenen** Geheimnisses einreichen
und den Einsatz des Gegners unabhängig vom Ergebnis einlösen. Der Bot dekodiert deshalb jede
BOLT11-Invoice selbst (`duellbot/rechnung.py`, ohne zusätzliche Abhängigkeit, getestet mit den
Testvektoren aus der BOLT11-Spezifikation) und lehnt sie ab, wenn eines nicht stimmt:

- Payment-Hash ≠ der vom Bot vorgegebene Hash
- Betrag fehlt oder ≠ Einsatz
- falsches Netzwerk (`NETZWERK`)
- läuft in weniger als `MIN_RESTLAUFZEIT_MINUTEN` ab
- CLTV-Delta kleiner als `MIN_CLTV_BLOECKE`

Die Signatur wird nicht geprüft. Eine gefälschte Signatur macht die Invoice nur unbezahlbar,
denn einlösen kann nur, wer das Preimage kennt.

## Wichtige Grenzen

- **Hold-Invoices mit fremdem Hash:** Laut Hydranet-Dev über API/CLI möglich. Die genauen Befehle fehlen noch. Bei LND wären es z. B. `lncli addholdinvoice <hash> <betrag>` und `settleinvoice <preimage>`.
- **Nur BOLT11:** Die Prüfung versteht Lightning-Invoices (`lnbc…`). Nutzt Hydranet (z. B. über Lithium) ein anderes Format, muss `rechnung.py` angepasst werden.
- **„Zahlung erhalten“ beruht auf Vertrauen:** Der Bot sieht nicht, ob eine Zahlung wirklich gesperrt eingegangen ist. Mit einer Status-Abfrage über die Hydranet-API ließe sich das automatisieren.
- **Laufzeit:** Gesperrte Zahlungen binden Kapital im Lightning-Netz und laufen nach der Invoice-Ablaufzeit bzw. dem CLTV-Limit ab. Geeignet für Matches von Minuten bis wenigen Stunden.
- **Vertrauen:** Schiedsrichter können kein Geld behalten, aber falsch entscheiden. Deshalb sind mehrere Bestätigungen nötig.
- **Geheimnisse** liegen in der lokalen SQLite-Datei (`duelle.db`). Wer darauf Zugriff hat, kann Ergebnisse vorwegnehmen. Schütze den Server.
- **Recht:** Geldeinsätze auf Spiele mit Zufallsanteil (z. B. Poker) können in Deutschland als Glücksspiel gelten. Vor dem öffentlichen Einsatz rechtlich prüfen lassen.

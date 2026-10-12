"""Prüfung von Lightning-Invoices (BOLT11), bevor der Gegner sie bezahlt.

Ohne Prüfung könnte ein Spieler eine Invoice mit dem Hash eines *eigenen*
Geheimnisses einreichen und sie dann unabhängig vom Ergebnis einlösen. Deshalb
nimmt der Bot nur Invoices an, deren Payment-Hash, Betrag und Laufzeit stimmen.

Die Signatur wird nicht geprüft. Eine gefälschte Signatur macht die Invoice
nur unbezahlbar und eröffnet keinen Betrug, denn einlösen kann nur, wer das
Preimage zum Hash kennt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ZEICHEN = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_HRP = re.compile(r"^ln(bcrt|bc|tbs|tb|sb)(\d+)?([munp])?$")
# Millisatoshi pro Einheit der Betragsangabe (1 BTC = 10^11 msat).
_MULTIPLIKATOR_MSAT = {None: 10**11, "m": 10**8, "u": 10**5, "n": 10**2}
_SIGNATUR_WOERTER = 104  # 65 Bytes
_TAG_HASH, _TAG_ABLAUF, _TAG_CLTV = 1, 6, 24

STANDARD_ABLAUF = 3600
STANDARD_CLTV = 18


class RechnungFehler(Exception):
    """Invoice ungültig oder passt nicht zum Duell."""


@dataclass(frozen=True)
class Rechnung:
    netzwerk: str
    betrag_msat: int | None
    zeitstempel: int
    ablauf_sekunden: int
    payment_hash: str
    min_final_cltv: int

    @property
    def ablauf_zeitpunkt(self) -> int:
        return self.zeitstempel + self.ablauf_sekunden


@dataclass(frozen=True)
class Regeln:
    netzwerk: str = "bc"
    min_restlaufzeit_sekunden: int = 600
    min_cltv: int = 40


def _polymod(werte: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for wert in werte:
        oben = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ wert
        for i in range(5):
            chk ^= generator[i] if (oben >> i) & 1 else 0
    return chk


def _hrp_erweitern(hrp: str) -> list[int]:
    return [ord(z) >> 5 for z in hrp] + [0] + [ord(z) & 31 for z in hrp]


def _als_zahl(woerter: list[int]) -> int:
    zahl = 0
    for w in woerter:
        zahl = zahl << 5 | w
    return zahl


def _als_bytes(woerter: list[int]) -> bytes:
    """5-Bit-Wörter zu Bytes; überzählige Padding-Bits am Ende fallen weg."""
    bits = len(woerter) * 5
    return (_als_zahl(woerter) >> (bits % 8)).to_bytes(bits // 8, "big")


def dekodieren(text: str) -> Rechnung:
    text = text.strip()
    if text.lower().startswith("lightning:"):
        text = text[len("lightning:"):]
    if text != text.lower() and text != text.upper():
        raise RechnungFehler("Ungültige Invoice (gemischte Groß-/Kleinschreibung).")
    text = text.lower()

    trenner = text.rfind("1")
    if trenner < 1:
        raise RechnungFehler("Das ist keine Lightning-Invoice.")
    hrp, daten = text[:trenner], text[trenner + 1:]
    if any(z not in _ZEICHEN for z in daten):
        raise RechnungFehler("Ungültige Zeichen in der Invoice.")
    woerter = [_ZEICHEN.index(z) for z in daten]
    if _polymod(_hrp_erweitern(hrp) + woerter) != 1:
        raise RechnungFehler("Prüfsumme falsch. Wurde die Invoice vollständig kopiert?")
    woerter = woerter[:-6]
    if len(woerter) < 7 + _SIGNATUR_WOERTER:
        raise RechnungFehler("Die Invoice ist zu kurz.")

    treffer = _HRP.match(hrp)
    if not treffer:
        raise RechnungFehler("Unbekanntes Netzwerk oder ungültiger Betrag in der Invoice.")
    netzwerk, ziffern, einheit = treffer.groups()
    betrag_msat = None
    if ziffern is not None:
        if einheit == "p":
            if int(ziffern) % 10:
                raise RechnungFehler("Ungültiger Betrag (Bruchteil eines Millisatoshi).")
            betrag_msat = int(ziffern) // 10
        else:
            betrag_msat = int(ziffern) * _MULTIPLIKATOR_MSAT[einheit]
    elif einheit is not None:
        raise RechnungFehler("Ungültiger Betrag in der Invoice.")

    zeitstempel = _als_zahl(woerter[:7])
    felder = woerter[7:-_SIGNATUR_WOERTER]
    payment_hash = None
    ablauf, cltv = STANDARD_ABLAUF, STANDARD_CLTV
    i = 0
    while i < len(felder):
        if i + 3 > len(felder):
            raise RechnungFehler("Beschädigte Invoice.")
        tag, laenge = felder[i], felder[i + 1] * 32 + felder[i + 2]
        inhalt = felder[i + 3:i + 3 + laenge]
        if len(inhalt) != laenge:
            raise RechnungFehler("Beschädigte Invoice.")
        if tag == _TAG_HASH and laenge == 52 and payment_hash is None:
            payment_hash = _als_bytes(inhalt).hex()
        elif tag == _TAG_ABLAUF:
            ablauf = _als_zahl(inhalt)
        elif tag == _TAG_CLTV:
            cltv = _als_zahl(inhalt)
        i += 3 + laenge

    if payment_hash is None:
        raise RechnungFehler("Die Invoice enthält keinen Payment-Hash.")
    return Rechnung(netzwerk, betrag_msat, zeitstempel, ablauf, payment_hash, cltv)


def pruefen(text: str, erwarteter_hash: str, betrag_sat: int, jetzt: float, regeln: Regeln) -> Rechnung:
    """Dekodiert die Invoice und prüft sie gegen das Duell. Wirft RechnungFehler mit Begründung."""
    r = dekodieren(text)
    if r.netzwerk != regeln.netzwerk:
        raise RechnungFehler(f"Falsches Netzwerk: „{r.netzwerk}“ statt „{regeln.netzwerk}“.")
    if r.payment_hash != erwarteter_hash.lower():
        raise RechnungFehler("Der Payment-Hash stimmt nicht. Erstelle die Invoice genau mit dem Hash, den der Bot dir angezeigt hat.")
    if r.betrag_msat is None:
        raise RechnungFehler("Die Invoice hat keinen Betrag. Bitte mit festem Betrag erstellen.")
    if r.betrag_msat != betrag_sat * 1000:
        raise RechnungFehler(f"Falscher Betrag: {r.betrag_msat / 1000:g} sat statt {betrag_sat} sat.")
    if r.ablauf_zeitpunkt - jetzt < regeln.min_restlaufzeit_sekunden:
        raise RechnungFehler(
            f"Die Invoice läuft zu bald ab. Sie muss noch mindestens {regeln.min_restlaufzeit_sekunden // 60} Minuten gültig sein."
        )
    if r.min_final_cltv < regeln.min_cltv:
        raise RechnungFehler(
            f"CLTV-Delta zu klein ({r.min_final_cltv} statt mindestens {regeln.min_cltv} Blöcke). "
            "Die Zahlung könnte sonst vor dem Spielende zurückgehen."
        )
    return r

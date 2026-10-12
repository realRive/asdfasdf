"""Zustandsmaschine für ein Duell. Enthält keinen Discord-Code und ist dadurch testbar.

Ablauf:
    OFFEN -> EINSATZ_AUSSTEHEND -> LAEUFT -> EINSPRUCHSFRIST -> ABGESCHLOSSEN
                                         └-> STREIT -> ABGESCHLOSSEN
    Vor dem Abschluss kann jederzeit ABGEBROCHEN werden.

Geld fließt nie über den Bot. Er erzeugt nur zwei Geheimnisse (Preimages):
S_A ("Herausforderer gewinnt") und S_B ("Gegner gewinnt"). Die Spieler sperren
ihre Einsätze gegenseitig über Lightning-Hold-Invoices mit den Hashes dieser
Geheimnisse. Erst wenn das Ergebnis feststeht, bekommt der Gewinner sein Geheimnis
und kann damit die Zahlung des Verlierers einlösen. Alle anderen Zahlungen laufen
ab und gehen automatisch an den Absender zurück.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
from enum import Enum

from .rechnung import Regeln, RechnungFehler, pruefen

UNENTSCHIEDEN = 0


class Status(str, Enum):
    OFFEN = "offen"
    EINSATZ_AUSSTEHEND = "einsatz_ausstehend"
    LAEUFT = "laeuft"
    EINSPRUCHSFRIST = "einspruchsfrist"
    STREIT = "streit"
    ABGESCHLOSSEN = "abgeschlossen"
    ABGEBROCHEN = "abgebrochen"


class DuellFehler(Exception):
    """Unzulässige Aktion. Die Meldung wird direkt dem Nutzer angezeigt."""


def payment_hash(preimage_hex: str) -> str:
    """Lightning-Payment-Hash: SHA-256 über die rohen Preimage-Bytes."""
    return hashlib.sha256(bytes.fromhex(preimage_hex)).hexdigest()


@dataclass
class Duell:
    id: int
    kanal_id: int
    herausforderer: int
    gegner: int
    spiel: str
    einsatz_sat: int
    status: Status = Status.OFFEN
    geheimnis_a: str = ""
    geheimnis_b: str = ""
    # Geprüfte Invoices: invoice_a stellt A aus (Hash A), B bezahlt sie. Umgekehrt für B.
    invoice_a: str = ""
    invoice_b: str = ""
    # Ein Spieler bestätigt, dass die Zahlung des anderen bei ihm gesperrt eingegangen ist.
    eingang_a: bool = False
    eingang_b: bool = False
    spieler_meldungen: dict[int, int] = field(default_factory=dict)
    schiri_stimmen: dict[int, int] = field(default_factory=dict)
    gewinner: int | None = None
    frist_ende: float | None = None

    # --- Hilfen -------------------------------------------------------------

    @property
    def spieler(self) -> tuple[int, int]:
        return (self.herausforderer, self.gegner)

    @property
    def hash_a(self) -> str:
        return payment_hash(self.geheimnis_a)

    @property
    def hash_b(self) -> str:
        return payment_hash(self.geheimnis_b)

    def geheimnis_fuer(self, nutzer: int) -> str:
        if self.status is not Status.ABGESCHLOSSEN:
            raise DuellFehler("Das Duell ist noch nicht abgeschlossen.")
        if self.gewinner == UNENTSCHIEDEN:
            raise DuellFehler("Unentschieden: Es wird kein Geheimnis freigegeben. Die Zahlungen laufen ab.")
        if nutzer != self.gewinner:
            raise DuellFehler("Nur der Gewinner erhält das Geheimnis.")
        return self.geheimnis_a if nutzer == self.herausforderer else self.geheimnis_b

    def _pruefe_status(self, *erlaubt: Status) -> None:
        if self.status not in erlaubt:
            raise DuellFehler(f"Das geht im Status „{self.status.value}“ nicht.")

    def _pruefe_spieler(self, nutzer: int) -> None:
        if nutzer not in self.spieler:
            raise DuellFehler("Du bist kein Spieler in diesem Duell.")

    # --- Übergänge ----------------------------------------------------------

    def annehmen(self, nutzer: int) -> None:
        self._pruefe_status(Status.OFFEN)
        if nutzer != self.gegner:
            raise DuellFehler("Nur der Herausgeforderte kann annehmen.")
        self.geheimnis_a = secrets.token_hex(32)
        self.geheimnis_b = secrets.token_hex(32)
        self.status = Status.EINSATZ_AUSSTEHEND

    def invoice_einreichen(self, nutzer: int, invoice: str, jetzt: float, regeln: Regeln) -> None:
        """Nimmt die Invoice eines Spielers nur an, wenn Hash, Betrag und Laufzeit stimmen."""
        self._pruefe_status(Status.EINSATZ_AUSSTEHEND)
        self._pruefe_spieler(nutzer)
        ist_a = nutzer == self.herausforderer
        if self.eingang_a if ist_a else self.eingang_b:
            raise DuellFehler("Du hast den Zahlungseingang schon bestätigt. Die Invoice kann nicht mehr geändert werden.")
        try:
            pruefen(invoice, self.hash_a if ist_a else self.hash_b, self.einsatz_sat, jetzt, regeln)
        except RechnungFehler as fehler:
            raise DuellFehler(f"Invoice abgelehnt: {fehler}") from fehler
        invoice = invoice.strip()
        if ist_a:
            self.invoice_a = invoice
        else:
            self.invoice_b = invoice

    def eingang_bestaetigen(self, nutzer: int) -> None:
        self._pruefe_status(Status.EINSATZ_AUSSTEHEND)
        self._pruefe_spieler(nutzer)
        if not (self.invoice_a if nutzer == self.herausforderer else self.invoice_b):
            raise DuellFehler("Reiche zuerst deine Invoice mit `/duell invoice` ein. Erst die geprüfte Invoice darf bezahlt werden.")
        if nutzer == self.herausforderer:
            self.eingang_a = True
        else:
            self.eingang_b = True
        if self.eingang_a and self.eingang_b:
            self.status = Status.LAEUFT

    def abbrechen(self, nutzer: int, ist_schiri: bool) -> None:
        self._pruefe_status(Status.OFFEN, Status.EINSATZ_AUSSTEHEND, Status.LAEUFT,
                            Status.EINSPRUCHSFRIST, Status.STREIT)
        spieler_darf = nutzer in self.spieler and self.status in (Status.OFFEN, Status.EINSATZ_AUSSTEHEND)
        if not (spieler_darf or ist_schiri):
            raise DuellFehler("Nach Spielbeginn kann nur ein Schiedsrichter abbrechen.")
        self.status = Status.ABGEBROCHEN

    def melden(self, nutzer: int, gewinner: int, ist_schiri: bool, jetzt: float,
               frist_sekunden: float, benoetigte_stimmen: int) -> bool:
        """Ergebnis melden. Gibt True zurück, wenn dadurch ein Ergebnis feststeht."""
        self._pruefe_status(Status.LAEUFT, Status.STREIT)
        if gewinner not in (*self.spieler, UNENTSCHIEDEN):
            raise DuellFehler("Ungültiger Gewinner.")

        if nutzer in self.spieler:
            if self.status is Status.STREIT:
                raise DuellFehler("Im Streitfall entscheiden nur Schiedsrichter.")
            self.spieler_meldungen[nutzer] = gewinner
            a = self.spieler_meldungen.get(self.herausforderer)
            b = self.spieler_meldungen.get(self.gegner)
            if a is not None and a == b:
                self._entscheiden(gewinner, jetzt, frist_sekunden, endgueltig=False)
                return True
            return False

        if not ist_schiri:
            raise DuellFehler("Nur Spieler oder Schiedsrichter können ein Ergebnis melden.")
        self.schiri_stimmen[nutzer] = gewinner
        if list(self.schiri_stimmen.values()).count(gewinner) >= benoetigte_stimmen:
            self._entscheiden(gewinner, jetzt, frist_sekunden, endgueltig=self.status is Status.STREIT)
            return True
        return False

    def _entscheiden(self, gewinner: int, jetzt: float, frist_sekunden: float, endgueltig: bool) -> None:
        self.gewinner = gewinner
        if endgueltig:
            self.status = Status.ABGESCHLOSSEN
            self.frist_ende = None
        else:
            self.status = Status.EINSPRUCHSFRIST
            self.frist_ende = jetzt + frist_sekunden

    def einspruch(self, nutzer: int, jetzt: float) -> None:
        self._pruefe_status(Status.EINSPRUCHSFRIST)
        self._pruefe_spieler(nutzer)
        if self.frist_ende is not None and jetzt >= self.frist_ende:
            raise DuellFehler("Die Einspruchsfrist ist abgelaufen.")
        self.status = Status.STREIT
        self.gewinner = None
        self.frist_ende = None
        self.schiri_stimmen.clear()

    def frist_pruefen(self, jetzt: float) -> bool:
        """Schließt das Duell ab, wenn die Einspruchsfrist vorbei ist. True bei Änderung."""
        if self.status is Status.EINSPRUCHSFRIST and self.frist_ende is not None and jetzt >= self.frist_ende:
            self.status = Status.ABGESCHLOSSEN
            self.frist_ende = None
            return True
        return False

    # --- Serialisierung -----------------------------------------------------

    def to_json(self) -> str:
        daten = asdict(self)
        daten["status"] = self.status.value
        return json.dumps(daten)

    @classmethod
    def from_json(cls, text: str) -> Duell:
        daten = json.loads(text)
        daten["status"] = Status(daten["status"])
        # JSON-Schlüssel sind Strings, Discord-IDs sind ints.
        daten["spieler_meldungen"] = {int(k): v for k, v in daten["spieler_meldungen"].items()}
        daten["schiri_stimmen"] = {int(k): v for k, v in daten["schiri_stimmen"].items()}
        return cls(**daten)

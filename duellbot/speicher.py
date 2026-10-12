"""SQLite-Speicher für Duelle. Damit überstehen laufende Duelle einen Neustart des Bots."""

from __future__ import annotations

import sqlite3

from .logik import Duell, Status


class Speicher:
    def __init__(self, pfad: str) -> None:
        self._db = sqlite3.connect(pfad)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS duelle (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT, daten TEXT)"
        )
        self._db.commit()

    def neu(self, kanal_id: int, herausforderer: int, gegner: int, spiel: str, einsatz: str) -> Duell:
        cur = self._db.execute("INSERT INTO duelle (status, daten) VALUES (?, '')", (Status.OFFEN.value,))
        duell = Duell(cur.lastrowid, kanal_id, herausforderer, gegner, spiel, einsatz)
        self.speichern(duell)
        return duell

    def laden(self, duell_id: int) -> Duell | None:
        zeile = self._db.execute("SELECT daten FROM duelle WHERE id = ?", (duell_id,)).fetchone()
        return Duell.from_json(zeile[0]) if zeile else None

    def speichern(self, duell: Duell) -> None:
        self._db.execute(
            "UPDATE duelle SET status = ?, daten = ? WHERE id = ?",
            (duell.status.value, duell.to_json(), duell.id),
        )
        self._db.commit()

    def mit_status(self, status: Status) -> list[Duell]:
        zeilen = self._db.execute("SELECT daten FROM duelle WHERE status = ?", (status.value,)).fetchall()
        return [Duell.from_json(z[0]) for z in zeilen]

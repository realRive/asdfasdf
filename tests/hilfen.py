"""Erzeugt Test-Invoices (mit Dummy-Signatur, die der Bot nicht prüft)."""

from duellbot.rechnung import _ZEICHEN, _hrp_erweitern, _polymod


def _woerter(zahl: int, anzahl: int) -> list[int]:
    return [(zahl >> 5 * (anzahl - 1 - i)) & 31 for i in range(anzahl)]


def _feld(tag: int, woerter: list[int]) -> list[int]:
    return [tag, len(woerter) // 32, len(woerter) % 32] + woerter


def invoice(payment_hash: str, betrag_sat: int | None, zeitstempel: int, ablauf: int = 3600,
            cltv: int = 80, netzwerk: str = "bc") -> str:
    hrp = f"ln{netzwerk}" + (f"{betrag_sat * 10}n" if betrag_sat is not None else "")
    # 256 Bit Hash + 4 Bit Padding = 52 Wörter
    daten = _woerter(zeitstempel, 7)
    daten += _feld(1, _woerter(int(payment_hash, 16) << 4, 52))
    daten += _feld(6, _woerter(ablauf, 4))
    daten += _feld(24, _woerter(cltv, 2))
    daten += [0] * 104  # Signatur
    chk = _polymod(_hrp_erweitern(hrp) + daten + [0] * 6) ^ 1
    daten += [(chk >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_ZEICHEN[w] for w in daten)

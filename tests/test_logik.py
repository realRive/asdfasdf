import hashlib

import pytest

from duellbot.logik import UNENTSCHIEDEN, Duell, DuellFehler, Status
from duellbot.rechnung import Regeln
from tests.hilfen import invoice

A, B, SCHIRI1, SCHIRI2, FREMD = 1, 2, 10, 11, 99
FRIST = 600
JETZT = 1_800_000_000
REGELN = Regeln()


def neues_duell() -> Duell:
    return Duell(id=1, kanal_id=5, herausforderer=A, gegner=B, spiel="CS2", einsatz_sat=150)


def angenommenes_duell() -> Duell:
    d = neues_duell()
    d.annehmen(B)
    d.invoice_einreichen(A, invoice(d.hash_a, 150, JETZT), JETZT, REGELN)
    d.invoice_einreichen(B, invoice(d.hash_b, 150, JETZT), JETZT, REGELN)
    return d


def laufendes_duell() -> Duell:
    d = angenommenes_duell()
    d.eingang_bestaetigen(A)
    d.eingang_bestaetigen(B)
    return d


def melden(d: Duell, nutzer: int, gewinner: int, schiri: bool = False, jetzt: float = 0) -> bool:
    return d.melden(nutzer, gewinner, schiri, jetzt, FRIST, benoetigte_stimmen=2)


def test_annehmen_erzeugt_lightning_kompatible_hashes():
    d = neues_duell()
    d.annehmen(B)
    assert d.status is Status.EINSATZ_AUSSTEHEND
    assert len(bytes.fromhex(d.geheimnis_a)) == 32
    assert d.hash_a == hashlib.sha256(bytes.fromhex(d.geheimnis_a)).hexdigest()
    assert d.geheimnis_a != d.geheimnis_b


def test_nur_gegner_kann_annehmen():
    d = neues_duell()
    with pytest.raises(DuellFehler):
        d.annehmen(A)


def test_spiel_startet_erst_wenn_beide_eingang_bestaetigen():
    d = angenommenes_duell()
    d.eingang_bestaetigen(A)
    assert d.status is Status.EINSATZ_AUSSTEHEND
    d.eingang_bestaetigen(B)
    assert d.status is Status.LAEUFT


def test_einige_spieler_dann_frist_dann_geheimnis_nur_fuer_gewinner():
    d = laufendes_duell()
    assert not melden(d, A, A)
    assert melden(d, B, A, jetzt=100)
    assert d.status is Status.EINSPRUCHSFRIST and d.frist_ende == 100 + FRIST
    with pytest.raises(DuellFehler):
        d.geheimnis_fuer(A)
    assert not d.frist_pruefen(100 + FRIST - 1)
    assert d.frist_pruefen(100 + FRIST)
    assert d.geheimnis_fuer(A) == d.geheimnis_a
    with pytest.raises(DuellFehler):
        d.geheimnis_fuer(B)


def test_uneinige_spieler_schiris_entscheiden():
    d = laufendes_duell()
    melden(d, A, A)
    assert not melden(d, B, B)
    assert d.status is Status.LAEUFT
    assert not melden(d, SCHIRI1, B, schiri=True)
    assert melden(d, SCHIRI2, B, schiri=True)
    assert d.gewinner == B and d.status is Status.EINSPRUCHSFRIST


def test_fremde_duerfen_nicht_melden():
    d = laufendes_duell()
    with pytest.raises(DuellFehler):
        melden(d, FREMD, A)


def test_einspruch_fuehrt_zu_endgueltiger_schiri_entscheidung():
    d = laufendes_duell()
    melden(d, A, A)
    melden(d, B, A, jetzt=0)
    d.einspruch(B, jetzt=10)
    assert d.status is Status.STREIT and d.gewinner is None
    with pytest.raises(DuellFehler):
        melden(d, A, A)
    melden(d, SCHIRI1, B, schiri=True)
    assert melden(d, SCHIRI2, B, schiri=True)
    assert d.status is Status.ABGESCHLOSSEN
    assert d.geheimnis_fuer(B) == d.geheimnis_b


def test_einspruch_nach_fristende_abgelehnt():
    d = laufendes_duell()
    melden(d, A, A)
    melden(d, B, A, jetzt=0)
    with pytest.raises(DuellFehler):
        d.einspruch(B, jetzt=FRIST)


def test_unentschieden_gibt_kein_geheimnis_frei():
    d = laufendes_duell()
    melden(d, A, UNENTSCHIEDEN)
    melden(d, B, UNENTSCHIEDEN)
    d.frist_pruefen(FRIST)
    assert d.status is Status.ABGESCHLOSSEN
    with pytest.raises(DuellFehler):
        d.geheimnis_fuer(A)


def test_nach_spielbeginn_bricht_nur_schiri_ab():
    d = laufendes_duell()
    with pytest.raises(DuellFehler):
        d.abbrechen(A, ist_schiri=False)
    d.abbrechen(SCHIRI1, ist_schiri=True)
    assert d.status is Status.ABGEBROCHEN


def test_json_rundreise():
    d = laufendes_duell()
    melden(d, A, A)
    melden(d, SCHIRI1, B, schiri=True)
    assert Duell.from_json(d.to_json()) == d


def test_eingang_erst_nach_gepruefter_invoice():
    d = neues_duell()
    d.annehmen(B)
    with pytest.raises(DuellFehler, match="Invoice"):
        d.eingang_bestaetigen(A)


def test_invoice_mit_fremdem_hash_wird_abgelehnt():
    d = neues_duell()
    d.annehmen(B)
    # A versucht, den Hash von B (oder einen eigenen) unterzuschieben.
    with pytest.raises(DuellFehler, match="Hash"):
        d.invoice_einreichen(A, invoice(d.hash_b, 150, JETZT), JETZT, REGELN)
    with pytest.raises(DuellFehler, match="Hash"):
        d.invoice_einreichen(A, invoice("00" * 32, 150, JETZT), JETZT, REGELN)
    assert d.invoice_a == ""


def test_invoice_nach_eingang_nicht_mehr_aenderbar():
    d = angenommenes_duell()
    d.eingang_bestaetigen(A)
    with pytest.raises(DuellFehler, match="schon bestätigt"):
        d.invoice_einreichen(A, invoice(d.hash_a, 150, JETZT), JETZT, REGELN)


def test_fremde_koennen_keine_invoice_einreichen():
    d = neues_duell()
    d.annehmen(B)
    with pytest.raises(DuellFehler):
        d.invoice_einreichen(FREMD, invoice(d.hash_a, 150, JETZT), JETZT, REGELN)

import pytest

from duellbot.rechnung import Regeln, RechnungFehler, dekodieren, pruefen
from tests.hilfen import invoice

# Testvektoren aus der BOLT11-Spezifikation (lightning/bolts, 11-payment-encoding.md)
KAFFEE = (
    "lnbc2500u1pvjluezsp5zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygspp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5"
    "rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpu9qrsgquk0rl77nj30yxdy8j9vdx85fkpmdla2087ne0xh8nhedh8w27kyke0lp53ut353s06fv3qfe"
    "gext0eh0ymjpf39tuven09sam30g4vgpfna3rh"
)
PICO = (
    "lnbc9678785340p1pwmna7lpp5gc3xfm08u9qy06djf8dfflhugl6p7lgza6dsjxq454gxhj9t7a0sd8dgfkx7cmtwd68yetpd5s9xar0wfjn5gpc8qhr"
    "sdfq24f5ggrxdaezqsnvda3kkum5wfjkzmfqf3jkgem9wgsyuctwdus9xgrcyqcjcgpzgfskx6eqf9hzqnteypzxz7fzypfhg6trddjhygrcyqezcgpzf"
    "ysywmm5ypxxjemgw3hxjmn8yptk7untd9hxwg3q2d6xjcmtv4ezq7pqxgsxzmnyyqcjqmt0wfjjq6t5v4khxsp5zyg3zyg3zyg3zyg3zyg3zyg3zyg3zy"
    "g3zyg3zyg3zyg3zyg3zygsxqyjw5qcqp2rzjq0gxwkzc8w6323m55m4jyxcjwmy7stt9hwkwe2qxmy8zpsgg7jcuwz87fcqqeuqqqyqqqqlgqqqqn3qq9"
    "q9qrsgqrvgkpnmps664wgkp43l22qsgdw4ve24aca4nymnxddlnp8vh9v2sdxlu5ywdxefsfvm0fq3sesf08uf6q9a2ke0hc9j6z6wlxg5z5kqpu2v9wz"
)
FALSCHE_PRUEFSUMME = (
    "lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpquwpc4curk03c9wlrswe78q4eyqc7d8d0xqzpuyk0sg5"
    "g70me25alkluzd2x62aysf2pyy8edtjeevuv4p2d5p76r4zkmneet7uvyakky2zr4cusd45tftc9c5fh0nnqpnl2jfll544esqchsrnt"
)
UNGUELTIGER_MULTIPLIKATOR = (
    "lnbc2500x1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq5xysxxatsyp3k7enxv4jsxqzpusp5zyg3zyg3zyg3zy"
    "g3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs9qrsgqrrzc4cvfue4zp3hggxp47ag7xnrlr8vgcmkjxk3j5jqethnumgkpqp23z9jclu3v0a7e0aruz"
    "366e9wqdykw6dxhdzcjjhldxq0w6wgqcnu43j"
)
SPEC_HASH = "0001020304050607080900010203040506070809000102030405060708090102"

HASH = "ab" * 32
JETZT = 1_800_000_000
REGELN = Regeln(netzwerk="bc", min_restlaufzeit_sekunden=600, min_cltv=40)


def test_spec_kaffee():
    r = dekodieren(KAFFEE)
    assert (r.netzwerk, r.betrag_msat, r.zeitstempel, r.ablauf_sekunden, r.min_final_cltv) == ("bc", 250_000_000, 1496314658, 60, 18)
    assert r.payment_hash == SPEC_HASH


def test_spec_pico_betrag_und_cltv():
    r = dekodieren("lightning:" + PICO.upper())
    assert r.betrag_msat == 967_878_534
    assert r.ablauf_sekunden == 604_800 and r.min_final_cltv == 10
    assert r.payment_hash == "462264ede7e14047e9b249da94fefc47f41f7d02ee9b091815a5506bc8abf75f"


@pytest.mark.parametrize("kaputt", [FALSCHE_PRUEFSUMME, UNGUELTIGER_MULTIPLIKATOR, KAFFEE[:-1], "LNbc" + KAFFEE[4:], "hallo"])
def test_spec_ungueltige_werden_abgelehnt(kaputt):
    with pytest.raises(RechnungFehler):
        dekodieren(kaputt)


def test_eigene_invoice_rundreise():
    r = dekodieren(invoice(HASH, 150, JETZT, ablauf=7200, cltv=80))
    assert (r.payment_hash, r.betrag_msat, r.ablauf_sekunden, r.min_final_cltv) == (HASH, 150_000, 7200, 80)


def test_passende_invoice_wird_angenommen():
    pruefen(invoice(HASH, 150, JETZT), HASH, 150, JETZT, REGELN)


@pytest.mark.parametrize("text, grund", [
    (invoice("cd" * 32, 150, JETZT), "Hash"),
    (invoice(HASH, 151, JETZT), "Betrag"),
    (invoice(HASH, None, JETZT), "keinen Betrag"),
    (invoice(HASH, 150, JETZT, ablauf=300), "läuft zu bald ab"),
    (invoice(HASH, 150, JETZT - 3600), "läuft zu bald ab"),
    (invoice(HASH, 150, JETZT, cltv=18), "CLTV"),
    (invoice(HASH, 150, JETZT, netzwerk="tb"), "Netzwerk"),
])
def test_unpassende_invoice_wird_abgelehnt(text, grund):
    with pytest.raises(RechnungFehler, match=grund):
        pruefen(text, HASH, 150, JETZT, REGELN)

"""Discord-Bot für 1v1-Duelle mit Einsatz über Lightning-Hold-Invoices.

Start: python -m duellbot.bot   (Konfiguration über Umgebungsvariablen, siehe .env.example)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .logik import UNENTSCHIEDEN, Duell, DuellFehler, Status
from .speicher import Speicher

TOKEN = os.environ.get("DISCORD_TOKEN", "")
GUILD_ID = int(os.environ["GUILD_ID"]) if os.environ.get("GUILD_ID") else None
SCHIRI_ROLLE = os.environ.get("SCHIRI_ROLLE", "Schiedsrichter")
BENOETIGTE_STIMMEN = int(os.environ.get("BENOETIGTE_BESTAETIGUNGEN", "2"))
FRIST_SEKUNDEN = float(os.environ.get("EINSPRUCHSFRIST_MINUTEN", "10")) * 60
DB_PFAD = os.environ.get("DB_PFAD", "duelle.db")

log = logging.getLogger("duellbot")
speicher = Speicher(DB_PFAD)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
gruppe = app_commands.Group(name="duell", description="1v1-Duelle mit Einsatz")


# --- Darstellung -------------------------------------------------------------

def ist_schiri(nutzer: discord.abc.User) -> bool:
    return isinstance(nutzer, discord.Member) and any(r.name == SCHIRI_ROLLE for r in nutzer.roles)


def name_gewinner(duell: Duell) -> str:
    return "Unentschieden" if duell.gewinner == UNENTSCHIEDEN else f"<@{duell.gewinner}>"


def embed(duell: Duell) -> discord.Embed:
    e = discord.Embed(title=f"Duell #{duell.id}: {duell.spiel}", colour=discord.Colour.orange())
    e.add_field(name="Herausforderer (A)", value=f"<@{duell.herausforderer}>")
    e.add_field(name="Gegner (B)", value=f"<@{duell.gegner}>")
    e.add_field(name="Einsatz", value=duell.einsatz)
    e.add_field(name="Status", value=duell.status.value, inline=False)

    if duell.status is Status.EINSATZ_AUSSTEHEND:
        e.add_field(name="Hash A (A gewinnt)", value=f"`{duell.hash_a}`", inline=False)
        e.add_field(name="Hash B (B gewinnt)", value=f"`{duell.hash_b}`", inline=False)
        e.add_field(
            name="So sperrt ihr den Einsatz",
            value=(
                f"1. **A** erstellt eine Hold-Invoice über {duell.einsatz} mit **Hash A** und schickt sie B. B bezahlt.\n"
                f"2. **B** erstellt eine Hold-Invoice über {duell.einsatz} mit **Hash B** und schickt sie A. A bezahlt.\n"
                "3. Sobald die Zahlung des anderen bei dir **gesperrt eingegangen** ist, klicke „Zahlung erhalten“.\n"
                "Das Spiel startet erst, wenn beide bestätigt haben."
            ),
            inline=False,
        )
        e.add_field(name="Bestätigt", value=f"A: {'✅' if duell.eingang_a else '⏳'}  B: {'✅' if duell.eingang_b else '⏳'}")
    elif duell.status is Status.LAEUFT:
        e.add_field(name="Ergebnis melden", value="Beide Spieler melden mit `/duell ergebnis`. Wenn ihr euch nicht einig seid, entscheiden Schiedsrichter.", inline=False)
    elif duell.status is Status.EINSPRUCHSFRIST:
        e.add_field(name="Vorläufiges Ergebnis", value=name_gewinner(duell))
        e.add_field(name="Einspruch bis", value=f"<t:{int(duell.frist_ende or 0)}:R>")
    elif duell.status is Status.STREIT:
        e.add_field(name="Streitfall", value=f"{BENOETIGTE_STIMMEN} Schiedsrichter (Rolle „{SCHIRI_ROLLE}“) müssen mit `/duell ergebnis` übereinstimmen.", inline=False)
    elif duell.status is Status.ABGESCHLOSSEN:
        e.colour = discord.Colour.green()
        e.add_field(name="Ergebnis", value=name_gewinner(duell))
        if duell.gewinner != UNENTSCHIEDEN:
            e.add_field(name="Auszahlung", value="Der Gewinner holt sich sein Geheimnis mit `/duell geheimnis` und löst damit die Hold-Invoice ein. Alle anderen Zahlungen laufen ab und gehen zurück.", inline=False)
        else:
            e.add_field(name="Auszahlung", value="Keine. Beide Hold-Invoices laufen ab oder werden storniert.", inline=False)
    elif duell.status is Status.ABGEBROCHEN:
        e.colour = discord.Colour.dark_grey()
        e.add_field(name="Abgebrochen", value="Es wird kein Geheimnis freigegeben. Gesperrte Zahlungen laufen ab und gehen zurück.", inline=False)
    return e


def knoepfe(duell: Duell) -> discord.ui.View:
    view = discord.ui.View(timeout=None)

    def knopf(label: str, aktion: str, stil: discord.ButtonStyle) -> None:
        view.add_item(discord.ui.Button(label=label, style=stil, custom_id=f"duell:{aktion}:{duell.id}"))

    if duell.status is Status.OFFEN:
        knopf("Annehmen", "annehmen", discord.ButtonStyle.success)
        knopf("Ablehnen", "ablehnen", discord.ButtonStyle.danger)
    elif duell.status is Status.EINSATZ_AUSSTEHEND:
        knopf("Zahlung erhalten", "eingang", discord.ButtonStyle.primary)
        knopf("Abbrechen", "ablehnen", discord.ButtonStyle.secondary)
    elif duell.status is Status.EINSPRUCHSFRIST:
        knopf("Einspruch", "einspruch", discord.ButtonStyle.danger)
    return view


# --- Gemeinsame Ausführung ----------------------------------------------------

async def ausfuehren(interaction: discord.Interaction, duell_id: int,
                     aktion: Callable[[Duell], object], als_update: bool = False) -> None:
    """Lädt das Duell, führt die Aktion aus und zeigt den neuen Stand an."""
    duell = speicher.laden(duell_id)
    if duell is None:
        await interaction.response.send_message(f"Duell #{duell_id} gibt es nicht.", ephemeral=True)
        return
    try:
        aktion(duell)
    except DuellFehler as fehler:
        await interaction.response.send_message(str(fehler), ephemeral=True)
        return
    speicher.speichern(duell)
    if als_update:
        await interaction.response.edit_message(embed=embed(duell), view=knoepfe(duell))
    else:
        await interaction.response.send_message(embed=embed(duell), view=knoepfe(duell))


@bot.listen("on_interaction")
async def knopf_gedrueckt(interaction: discord.Interaction) -> None:
    if interaction.type is not discord.InteractionType.component:
        return
    teile = (interaction.data or {}).get("custom_id", "").split(":")
    if len(teile) != 3 or teile[0] != "duell":
        return
    _, name, duell_id = teile
    nutzer = interaction.user
    aktionen: dict[str, Callable[[Duell], object]] = {
        "annehmen": lambda d: d.annehmen(nutzer.id),
        "ablehnen": lambda d: d.abbrechen(nutzer.id, ist_schiri(nutzer)),
        "eingang": lambda d: d.eingang_bestaetigen(nutzer.id),
        "einspruch": lambda d: d.einspruch(nutzer.id, time.time()),
    }
    if name in aktionen:
        await ausfuehren(interaction, int(duell_id), aktionen[name], als_update=True)


# --- Slash-Befehle -------------------------------------------------------------

@gruppe.command(name="herausfordern", description="Fordere jemanden zu einem Duell heraus")
@app_commands.describe(gegner="Wen forderst du heraus?", spiel="z. B. CS2 1v1 Aim-Map", einsatz="z. B. 0,10 € oder 300 sat")
async def herausfordern(interaction: discord.Interaction, gegner: discord.Member, spiel: str, einsatz: str) -> None:
    if gegner.id == interaction.user.id or gegner.bot:
        await interaction.response.send_message("Such dir einen echten Gegner. 🙂", ephemeral=True)
        return
    duell = speicher.neu(interaction.channel_id or 0, interaction.user.id, gegner.id, spiel, einsatz)
    await interaction.response.send_message(
        content=f"{gegner.mention}, du wurdest herausgefordert!", embed=embed(duell), view=knoepfe(duell)
    )


@gruppe.command(name="ergebnis", description="Ergebnis melden (Spieler oder Schiedsrichter)")
@app_commands.choices(ergebnis=[
    app_commands.Choice(name="Herausforderer (A) gewinnt", value="a"),
    app_commands.Choice(name="Gegner (B) gewinnt", value="b"),
    app_commands.Choice(name="Unentschieden / ungültig", value="x"),
])
async def ergebnis(interaction: discord.Interaction, duell_id: int, ergebnis: app_commands.Choice[str]) -> None:
    def aktion(d: Duell) -> None:
        gewinner = {"a": d.herausforderer, "b": d.gegner, "x": UNENTSCHIEDEN}[ergebnis.value]
        d.melden(interaction.user.id, gewinner, ist_schiri(interaction.user), time.time(),
                 FRIST_SEKUNDEN, BENOETIGTE_STIMMEN)
    await ausfuehren(interaction, duell_id, aktion)


@gruppe.command(name="einspruch", description="Einspruch gegen das vorläufige Ergebnis")
async def einspruch(interaction: discord.Interaction, duell_id: int) -> None:
    await ausfuehren(interaction, duell_id, lambda d: d.einspruch(interaction.user.id, time.time()))


@gruppe.command(name="abbrechen", description="Duell abbrechen (Spieler vor Spielbeginn, Schiedsrichter jederzeit)")
async def abbrechen(interaction: discord.Interaction, duell_id: int) -> None:
    await ausfuehren(interaction, duell_id, lambda d: d.abbrechen(interaction.user.id, ist_schiri(interaction.user)))


@gruppe.command(name="info", description="Aktuellen Stand eines Duells anzeigen")
async def info(interaction: discord.Interaction, duell_id: int) -> None:
    await ausfuehren(interaction, duell_id, lambda d: None)


@gruppe.command(name="geheimnis", description="Als Gewinner das Preimage zum Einlösen abholen (nur für dich sichtbar)")
async def geheimnis(interaction: discord.Interaction, duell_id: int) -> None:
    duell = speicher.laden(duell_id)
    if duell is None:
        await interaction.response.send_message(f"Duell #{duell_id} gibt es nicht.", ephemeral=True)
        return
    try:
        preimage = duell.geheimnis_fuer(interaction.user.id)
    except DuellFehler as fehler:
        await interaction.response.send_message(str(fehler), ephemeral=True)
        return
    await interaction.response.send_message(
        f"Dein Preimage für Duell #{duell.id}:\n`{preimage}`\n"
        "Löse damit die Hold-Invoice ein, die der Verlierer bezahlt hat. Gib es niemandem sonst.",
        ephemeral=True,
    )


# --- Hintergrund: Einspruchsfristen ------------------------------------------

@tasks.loop(seconds=20)
async def fristen_pruefen() -> None:
    jetzt = time.time()
    for duell in speicher.mit_status(Status.EINSPRUCHSFRIST):
        if not duell.frist_pruefen(jetzt):
            continue
        speicher.speichern(duell)
        kanal = bot.get_channel(duell.kanal_id)
        if isinstance(kanal, discord.abc.Messageable):
            await kanal.send(content=f"Duell #{duell.id} ist entschieden: {name_gewinner(duell)}", embed=embed(duell))


@bot.event
async def setup_hook() -> None:
    bot.tree.add_command(gruppe)
    if GUILD_ID:
        ziel = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=ziel)
        await bot.tree.sync(guild=ziel)
    else:
        await bot.tree.sync()
    fristen_pruefen.start()


@bot.event
async def on_ready() -> None:
    log.info("Eingeloggt als %s", bot.user)


def main() -> None:
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN fehlt (siehe .env.example).")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()

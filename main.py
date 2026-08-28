import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands

# Nastavenie oprávnení (Intents)
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Databázové pripojenie
conn = sqlite3.connect('databaza.db')
cursor = conn.cursor()

# Vytvorenie tabuliek, ak neexistujú
cursor.execute('''
    CREATE TABLE IF NOT EXISTS aktivity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        hodiny REAL
    )
''')
conn.commit()

# --- PRÍKAZY BOT_TREE ---

@bot.tree.command(name="aktivita", description="Zaznamenaj odpracované hodiny")
async def aktivita(interaction: discord.Interaction, hodiny: float):
    cursor.execute("INSERT INTO aktivity (user_id, hodiny) VALUES (?, ?)", (interaction.user.id, hodiny))
    conn.commit()
    await interaction.response.send_message(f"✅ Zaznamenaných {hodiny} hodín pre {interaction.user.mention}.", ephemeral=True)

@bot.tree.command(name="kontrolaaktivity", description="Skontroluj celkový počet hodín")
@app_commands.checks.has_permissions(administrator=True)
async def checkaktivita(interaction: discord.Interaction):
    cursor.execute("SELECT SUM(hodiny) FROM aktivity")
    vysledok = cursor.fetchone()[0]
    celkovo = vysledok if vysledok else 0
    await interaction.response.send_message(f"📊 Celkovo odpracované hodiny všetkých zamestnancov: **{celkovo}** hodín.", ephemeral=True)

@bot.tree.command(name="odstranitaktivitu", description="Vymaž všetky záznamy aktivít")
@app_commands.checks.has_permissions(administrator=True)
async def deleteaktivita(interaction: discord.Interaction):
    cursor.execute("DELETE FROM aktivity")
    conn.commit()
    await interaction.response.send_message("🗑️ Všetky záznamy aktivít boli vymazané.", ephemeral=True)

# --- SPRACOVANIE CHÝB PRÁV ---

@checkaktivita.error
@deleteaktivita.error
async def admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Tento príkaz môžu použiť iba administrátori.", ephemeral=True)

# --- UDALOSŤ SPUSTENIA ---

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot {bot.user} je online a príkazy sú synchronizované!")

# --- SPUSTENIE BOTA ---
bot.run(os.getenv('DISCORD_TOKEN'))

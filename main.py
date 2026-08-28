import sqlite3
import re
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from discord import app_commands

# --- CONFIG ---
TOKEN = "MTU0MjgyMjczNDg3NzI5ODc3OA.GFtrDL.3QXEDcVj6SUOfTsqlL5YqIDbDngC46IAaiW7mM"
ACTIVITY_CHANNEL_ID = 1542831116866551809

# --- DATABÁZA ---
conn = sqlite3.connect("activity.db")
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date TEXT,
        hours REAL
    )
''')
conn.commit()

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# --- HELPER FUNCTIONS ---
def parse_time(time_str):
    """Prevedie string XX:YY na datetime objekt."""
    try:
        return datetime.strptime(time_str, "%H:%M")
    except ValueError:
        return None

def calculate_hours(start_str, end_str):
    """Vypočíta rozdiel v hodinách medzi dvoma časmi."""
    t1 = parse_time(start_str)
    t2 = parse_time(end_str)
    if not t1 or not t2:
        return None
    
    # Ak je koniec skôr ako začiatok, predpokladáme prechod cez polnoc
    if t2 <= t1:
        t2 += timedelta(days=1)
    
    diff = t2 - t1
    return diff.total_seconds() / 3600

# --- UI COMPONENTS ---
class TimeInputModal(discord.ui.Modal, title="Zadaj čas aktivity"):
    time_from = discord.ui.TextInput(
        label="Čas OD (formát HH:MM)",
        placeholder="napr. 14:00",
        min_length=5,
        max_length=5
    )
    time_to = discord.ui.TextInput(
        label="Čas DO (formát HH:MM)",
        placeholder="napr. 18:30",
        min_length=5,
        max_length=5
    )

    def __init__(self, selected_date):
        super().__init__()
        self.selected_date = selected_date

    async def on_submit(self, interaction: discord.Interaction):
        start = self.time_from.value.strip()
        end = self.time_to.value.strip()

        hours = calculate_hours(start, end)
        if hours is None:
            await interaction.response.send_message("❌ Neplatný formát času! Použi formát **HH:MM** (napr. 14:00).", ephemeral=True)
            return

        # Uloženie do databázy
        cursor.execute("INSERT INTO activities (user_id, date, hours) VALUES (?, ?, ?)",
                       (interaction.user.id, self.selected_date, hours))
        conn.commit()

        # Odozva užívateľovi (súkromná)
        await interaction.response.send_message(f"✅ Aktivita pre deň **{self.selected_date}** ({start} - {end}) bola úspešne zaznamenaná ({hours:.2f} hodín).", ephemeral=True)

        # Odoslanie správy do predvoleného kanála
        target_channel = interaction.guild.get_channel(ACTIVITY_CHANNEL_ID)
        if target_channel:
            embed = discord.Embed(title="📝 Nový záznam aktivity", color=discord.Color.blue())
            embed.add_field(name="Hráč", value=interaction.user.mention, inline=True)
            embed.add_field(name="Dátum", value=self.selected_date, inline=True)
            embed.add_field(name="Trvanie", value=f"{start} - {end} ({hours:.2f} hod)", inline=False)
            embed.set_footer(text=f"ID Užívateľa: {interaction.user.id}")
            await target_channel.send(embed=embed)

class DateDropdown(discord.ui.Select):
    def __init__(self):
        options = []
        today = datetime.now()
        # Ponúkne posledných 7 dní na výber
        for i in range(7):
            day = today - timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            day_name = day.strftime("%A")
            options.append(discord.SelectOption(label=f"{date_str} ({day_name})", value=date_str))

        super().__init__(placeholder="Vyber dátum aktivity...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_date = self.values[0]
        # Otvorí modal pre zadanie času
        await interaction.response.send_modal(TimeInputModal(selected_date))

class DatePickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(DateDropdown())

# --- PRÍKAZY ---

@bot.tree.command(name="aktivita", description="Zaznamenať novú aktivitu")
async def aktivita(interaction: discord.Interaction):
    await interaction.response.send_message("Vyber dátum, pre ktorý chceš zadať aktivitu:", view=DatePickerView(), ephemeral=True)

@bot.tree.command(name="checkaktivita", description="Skontrolovať celkový odpracovaný čas hráča")
@app_commands.checks.has_permissions(administrator=True)
async def checkaktivita(interaction: discord.Interaction, hrac: discord.Member):
    cursor.execute("SELECT SUM(hours) FROM activities WHERE user_id = ?", (hrac.id,))
    result = cursor.fetchone()[0]
    total_hours = result if result else 0.0

    await interaction.response.send_message(f"📊 Hráč **{hrac.display_name}** má celkovo odpracované: **{total_hours:.2f} hodín**.")

@bot.tree.command(name="deleteaktivita", description="Vymazať záznamy aktivity hráča")
@app_commands.checks.has_permissions(administrator=True)
async def deleteaktivita(interaction: discord.Interaction, hrac: discord.Member):
    cursor.execute("DELETE FROM activities WHERE user_id = ?", (hrac.id,))
    conn.commit()

    await interaction.response.send_message(f"🗑️ Záznamy o aktivite pre hráča **{hrac.display_name}** boli úspešne vymazané.")

# Chybové hlásenie pri absencii práv
@checkaktivita.error
@deleteaktivita.error
async def admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Tento príkaz môžu použiť iba administrátori.", ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot {bot.user} je online a príkazy sú synchronizované!")

bot.run(TOKEN)

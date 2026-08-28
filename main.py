import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Pripojenie k databáze
conn = sqlite3.connect("databaza.db")
cursor = conn.cursor()

# Vytvorenie tabuliek
cursor.execute("CREATE TABLE IF NOT EXISTS activity (user_id INTEGER PRIMARY KEY, start_time TEXT, total_time INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS pay (user_id INTEGER PRIMARY KEY, hourly_rate REAL DEFAULT 0.0)")
cursor.execute("CREATE TABLE IF NOT EXISTS role_percents (role_id INTEGER PRIMARY KEY, percent REAL DEFAULT 100.0)")
conn.commit()

class ActivityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Začať aktivitu", style=discord.ButtonStyle.success, custom_id="start_act")
    async def start_activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        now = datetime.datetime.now().isoformat()
        
        cursor.execute("SELECT start_time FROM activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row and row[0] is not None:
            await interaction.response.send_message("Už máš spustenú aktivitu!", ephemeral=True)
            return

        cursor.execute("INSERT OR REPLACE INTO activity (user_id, start_time, total_time) VALUES (?, ?, COALESCE((SELECT total_time FROM activity WHERE user_id = ?), 0))", (user_id, now, user_id))
        conn.commit()
        
        await interaction.response.send_message("Aktivita bola spustená!", ephemeral=True)

    @discord.ui.button(label="Ukončiť aktivitu", style=discord.ButtonStyle.danger, custom_id="stop_act")
    async def stop_activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        cursor.execute("SELECT start_time, total_time FROM activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if not row or row[0] is None:
            await interaction.response.send_message("Nemáš spustenú žiadnu aktivitu!", ephemeral=True)
            return

        start_time = datetime.datetime.fromisoformat(row[0])
        now = datetime.datetime.now()
        duration = int((now - start_time).total_seconds())
        
        new_total = row[1] + duration
        
        cursor.execute("UPDATE activity SET start_time = NULL, total_time = ? WHERE user_id = ?", (new_total, user_id))
        conn.commit()
        
        minutes = duration // 60
        await interaction.response.send_message(f"Aktivita bola ukončená! Trvala {minutes} minút.", ephemeral=True)

@bot.event
async def on_ready():
    bot.add_view(ActivityView())
    await bot.tree.sync()
    print(f"Bot {bot.user} je online a príkazy sú synchronizované!")

# Príkaz na panel
@bot.tree.command(name="panel", description="Odošle panel na správu aktivity")
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(title="Správa Aktivity", description="Klikni na tlačidlo nižšie pre zapnutie alebo vypnutie aktivity.", color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, view=ActivityView())

# Príkaz na nastavenie základnej hodinovej mzdy
@bot.tree.command(name="nastavitvyplatu", description="Nastaví základnú hodinovú mzdu pre používateľa")
@app_commands.checks.has_permissions(administrator=True)
async def nastavitvyplatu(interaction: discord.Interaction, uzivatel: discord.Member, mzda: float):
    cursor.execute("INSERT OR REPLACE INTO pay (user_id, hourly_rate) VALUES (?, ?)", (uzivatel.id, mzda))
    conn.commit()
    await interaction.response.send_message(f"Základná mzda pre {uzivatel.mention} bola nastavená na {mzda}€/hod.", ephemeral=True)

# Nastavenie percent pre konkrétnu rolu (napr. Oprava, Tuning)
@bot.tree.command(name="nastavitpercentarole", description="Nastaví percento výplaty pre konkrétnu rolu")
@app_commands.checks.has_permissions(administrator=True)
async def nastavitpercentarole(interaction: discord.Interaction, rola: discord.Role, percento: float):
    cursor.execute("INSERT OR REPLACE INTO role_percents (role_id, percent) VALUES (?, ?)", (rola.id, percento))
    conn.commit()
    await interaction.response.send_message(f"Rola **{rola.name}** má teraz nastavených **{percento}%** z výplaty.", ephemeral=True)

# PRÍKAZ: Výpočet výplaty na základe času a percenta role
@bot.tree.command(name="vyplatazam", description="Zobrazí výplatu zamestnanca podľa jeho role a odpracovaného času")
async def vyplatazam(interaction: discord.Interaction, hrac: discord.Member):
    user_id = hrac.id
    
    cursor.execute("SELECT total_time FROM activity WHERE user_id = ?", (user_id,))
    act_row = cursor.fetchone()
    total_seconds = act_row[0] if act_row else 0

    cursor.execute("SELECT hourly_rate FROM pay WHERE user_id = ?", (user_id,))
    pay_row = cursor.fetchone()
    rate = pay_row[0] if pay_row else 0.0

    user_role_ids = [role.id for role in hrac.roles]
    percent = 100.0
    applied_role_name = "Základná (bez špeciálnej role)"

    if user_role_ids:
        placeholders = ','.join('?' for _ in user_role_ids)
        cursor.execute(f"SELECT role_id, percent FROM role_percents WHERE role_id IN ({placeholders}) ORDER BY percent DESC", user_role_ids)
        best_role = cursor.fetchone()
        if best_role:
            role_obj = interaction.guild.get_role(best_role[0])
            if role_obj:
                applied_role_name = role_obj.name
            percent = best_role[1]

    hours = total_seconds / 3600
    base_pay = hours * rate
    final_pay = base_pay * (percent / 100.0)

    embed = discord.Embed(title=f"Výplata zamestnanca: {hrac.display_name}", color=discord.Color.green())
    embed.add_field(name="Odpracovaný čas", value=f"{int(hours)} hod. {int((total_seconds % 3600) // 60)} min.", inline=False)
    embed.add_field(name="Základná mzda", value=f"{rate:.2f} €/hod", inline=False)
    embed.add_field(name="Aplikovaná rola / Kategória", value=f"{applied_role_name} ({percent}%)", inline=False)
    embed.add_field(name="Celková výplata", value=f"**{final_pay:.2f} €**", inline=False)
    
    await interaction.response.send_message(embed=embed)

bot.run("TOKEN")

import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime
import os

# ---------------------------------------------------------
# BOT SETUP & CONFIGURATION
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------
conn = sqlite3.connect("databaza.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS activity (
    user_id INTEGER PRIMARY KEY,
    start_time TEXT,
    total_time INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pay (
    user_id INTEGER PRIMARY KEY,
    hourly_rate REAL DEFAULT 0.0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS role_percents (
    role_id INTEGER PRIMARY KEY,
    percent REAL DEFAULT 100.0
)
""")
conn.commit()

# ---------------------------------------------------------
# UI COMPONENTS (BUTTONS & VIEWS)
# ---------------------------------------------------------
class ActivityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Začať aktivitu", 
        style=discord.ButtonStyle.success, 
        custom_id="start_act",
        emoji="▶️"
    )
    async def start_activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        now_str = datetime.datetime.now().isoformat()
        
        cursor.execute("SELECT start_time FROM activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row and row[0] is not None:
            embed = discord.Embed(
                title="⚠️ Aktivita už prebieha",
                description="Už máš spustenú aktivitu! Pred opätovným spustením ju musíš najprv ukončiť.",
                color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        cursor.execute("""
        INSERT OR REPLACE INTO activity (user_id, start_time, total_time) 
        VALUES (?, ?, COALESCE((SELECT total_time FROM activity WHERE user_id = ?), 0))
        """, (user_id, now_str, user_id))
        conn.commit()
        
        embed = discord.Embed(
            title="✅ Aktivita spustená",
            description=f"Aktivita bola úspešne zaznamenaná o <t:{int(datetime.datetime.now().timestamp())}:T>.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Ukončiť aktivitu", 
        style=discord.ButtonStyle.danger, 
        custom_id="stop_act",
        emoji="⏹️"
    )
    async def stop_activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        cursor.execute("SELECT start_time, total_time FROM activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if not row or row[0] is None:
            embed = discord.Embed(
                title="⚠️ Žiadna aktívna relácia",
                description="Nemáš spustenú žiadnu aktivitu!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        start_time = datetime.datetime.fromisoformat(row[0])
        now = datetime.datetime.now()
        duration = int((now - start_time).total_seconds())
        
        new_total = (row[1] or 0) + duration
        
        cursor.execute("UPDATE activity SET start_time = NULL, total_time = ? WHERE user_id = ?", (new_total, user_id))
        conn.commit()
        
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        
        embed = discord.Embed(
            title="🛑 Aktivita ukončená",
            description=f"Trvanie tejto relácie: **{hours}h {minutes}m {seconds}s**.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------------------------------------------------
# BOT EVENTS
# ---------------------------------------------------------
@bot.event
async def on_ready():
    bot.add_view(ActivityView())
    try:
        synced = await bot.tree.sync()
        print(f"Synchronizovaných {len(synced)} aplikovaných (slash) príkazy.")
    except Exception as e:
        print(f"Chyba pri synchronizácii príkazov: {e}")
        
    print(f"Bot {bot.user} je plne online a pripravený!")

# ---------------------------------------------------------
# SLASH COMMANDS
# ---------------------------------------------------------

# 1. PANEL PRÍKAZ
@bot.tree.command(name="panel", description="Odošle hlavný panel pre správy aktivity")
@app_commands.checks.has_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💼 Systém Sledovania Aktivity",
        description="Kliknutím na tlačidlá nižšie spravuješ svoj odpracovaný čas v službe.\n\n"
                    "▶️ **Začať aktivitu:** Spustí počítanie času.\n"
                    "⏹️ **Ukončiť aktivitu:** Zastaví počítanie a pripočíta čas k tvojmu profilu.",
        color=discord.Color.dark_blue()
    )
    embed.set_footer(text="Systém správy zamestnancov")
    await interaction.channel.send(embed=embed, view=ActivityView())
    await interaction.response.send_message("Panel bol úspešne odoslaný!", ephemeral=True)

# 2. NASTAVENIE MZDY
@bot.tree.command(name="nastavitvyplatu", description="Nastaví základnú hodinovú mzdu pre používateľa")
@app_commands.checks.has_permissions(administrator=True)
async def nastavitvyplatu(interaction: discord.Interaction, uzivatel: discord.Member, mzda: float):
    if mzda < 0:
        await interaction.response.send_message("Mzda nemôže byť záporná!", ephemeral=True)
        return

    cursor.execute("INSERT OR REPLACE INTO pay (user_id, hourly_rate) VALUES (?, ?)", (uzivatel.id, mzda))
    conn.commit()
    
    embed = discord.Embed(
        title="💰 Mzda Nastavená",
        description=f"Základná hodinová mzda pre {uzivatel.mention} bola nastavená na **{mzda:.2f} €/hod**.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# 3. NASTAVENIE PERCENT ROLE
@bot.tree.command(name="nastavitpercentarole", description="Nastaví percento výplaty pre konkrétnu rolu")
@app_commands.checks.has_permissions(administrator=True)
async def nastavitpercentarole(interaction: discord.Interaction, rola: discord.Role, percento: float):
    if percento < 0:
        await interaction.response.send_message("Percento nemôže byť záporné!", ephemeral=True)
        return

    cursor.execute("INSERT OR REPLACE INTO role_percents (role_id, percent) VALUES (?, ?)", (rola.id, percento))
    conn.commit()
    
    embed = discord.Embed(
        title="📊 Percento Role Nastavené",
        description=f"Rola {rola.mention} má odteraz nastavené násobenie výplaty na **{percento}%**.",
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# 4. ZOBRAZENIE PERCENT VŠETKÝCH RÓL
@bot.tree.command(name="zoznamporcent", description="Zobrazí zoznam všetkých nastavených percent pre role")
@app_commands.checks.has_permissions(administrator=True)
async def zoznamporcent(interaction: discord.Interaction):
    cursor.execute("SELECT role_id, percent FROM role_percents")
    rows = cursor.fetchall()
    
    if not rows:
        await interaction.response.send_message("Nenašli sa žiadne nastavené percentá ról.", ephemeral=True)
        return
        
    embed = discord.Embed(title="📋 Prehľad percent ról", color=discord.Color.blue())
    for role_id, percent in rows:
        role = interaction.guild.get_role(role_id)
        role_name = role.name if role else f"Neznáma rola ({role_id})"
        embed.add_field(name=role_name, value=f"{percent}%", inline=False)
        
    await interaction.response.send_message(embed=embed, ephemeral=True)

# 5. VÝPOČET VÝPLATY PRE ZAMESTNANCA
@bot.tree.command(name="vyplatazam", description="Zobrazí podrobný výpočet výplaty pre konkrétneho zamestnanca")
async def vyplatazam(interaction: discord.Interaction, hrac: discord.Member):
    user_id = hrac.id
    
    cursor.execute("SELECT total_time FROM activity WHERE user_id = ?", (user_id,))
    act_row = cursor.fetchone()
    total_seconds = act_row[0] if act_row and act_row[0] else 0

    cursor.execute("SELECT hourly_rate FROM pay WHERE user_id = ?", (user_id,))
    pay_row = cursor.fetchone()
    rate = pay_row[0] if pay_row and pay_row[0] else 0.0

    user_role_ids = [role.id for role in hrac.roles]
    percent = 100.0
    applied_role_name = "Základná (Bez špeciálnej role)"

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

    formatted_hours = int(hours)
    formatted_minutes = int((total_seconds % 3600) // 60)

    embed = discord.Embed(title=f"💳 Výplatná Páska: {hrac.display_name}", color=discord.Color.gold())
    embed.set_thumbnail(url=hrac.display_avatar.url)
    embed.add_field(name="⏱️ Odpracovaný čas", value=f"{formatted_hours} hod. {formatted_minutes} min.", inline=False)
    embed.add_field(name="💵 Základná mzda", value=f"{rate:.2f} €/hod", inline=True)
    embed.add_field(name="🏷️ Aplikovaná rola", value=f"{applied_role_name} ({percent}%)", inline=True)
    embed.add_field(name="💶 Finálna výplata", value=f"**{final_pay:.2f} €**", inline=False)
    
    await interaction.response.send_message(embed=embed)

# 6. MOJA AKTIVITA (PRE HRÁČA)
@bot.tree.command(name="mojaaktivita", description="Zobrazí tvoju odpracovanú aktivitu")
async def mojaaktivita(interaction: discord.Interaction):
    cursor.execute("SELECT start_time, total_time FROM activity WHERE user_id = ?", (interaction.user.id,))
    row = cursor.fetchone()
    
    total_seconds = row[1] if row and row[1] else 0
    is_active = row and row[0] is not None
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    
    status_str = "🟢 Práve v službe" if is_active else "🔴 Mimo služby"
    
    embed = discord.Embed(title=f"📊 Aktivita používateľa {interaction.user.display_name}", color=discord.Color.blue())
    embed.add_field(name="Stav", value=status_str, inline=False)
    embed.add_field(name="Odpracovaný čas", value=f"{hours} hodín a {minutes} minút", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# 7. RESET ČASU JEDNÉHO HRÁČA
@bot.tree.command(name="resetcasu", description="Vynuluje odpracovaný čas pre konkrétneho hráča")
@app_commands.checks.has_permissions(administrator=True)
async def resetcasu(interaction: discord.Interaction, uzivatel: discord.Member):
    cursor.execute("UPDATE activity SET total_time = 0 WHERE user_id = ?", (uzivatel.id,))
    conn.commit()
    
    embed = discord.Embed(
        title="🔄 Čas Vynulovaný",
        description=f"Odpracovaný čas pre {uzivatel.mention} bol úspešne resetovaný na 0.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# 8. RESET ČASU VŠETKÝCH HRÁČOV
@bot.tree.command(name="resetvsetkych", description="Vynuluje odpracovaný čas pre VŠETKÝCH hráčov")
@app_commands.checks.has_permissions(administrator=True)
async def resetvsetkych(interaction: discord.Interaction):
    cursor.execute("UPDATE activity SET total_time = 0")
    conn.commit()
    
    embed = discord.Embed(
        title="⚠️ Hromadný Reset",
        description="Odpracovaný čas bol úspešne vynulovaný pre **všetkých** používateľov v databáze!",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------------------------------------------------
# RUN BOT VIA ENVIRONMENT VARIABLE
# ---------------------------------------------------------
bot.run(os.getenv("TOKEN"))

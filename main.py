import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime

intents = discord.Intents.default()
intents.members = True  # Potrebné na čítanie rolí členov
bot = commands.Bot(command_prefix="!", intents=intents)

# Pripojenie k databáze
conn = sqlite3.connect("databaza.db")
cursor = conn.cursor()

# Vytvorenie tabuliek
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

# Nová tabuľka pre percentá podľa rolí
cursor.execute("""
CREATE TABLE IF NOT EXISTS role_percents (
    role_id INTEGER PRIMARY KEY,
    percent REAL DEFAULT 100.0
)
""")
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

# NOVÝ PRÍKAZ: Nastavenie percent pre konkrétnu rolu (napr. Oprava, Tuning)
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
    
    # Nájdeme odpracovaný čas
    cursor.execute("SELECT total_time FROM activity WHERE user_id = ?", (user_id,))
    act_row = cursor.fetchone()
    total_seconds = act_row[0] if act_row else 0

    # Nájdeme základnú hodinovú mzdu
    cursor.execute("SELECT hourly_rate FROM pay WHERE user_id = ?", (user_id,))
    pay_row = cursor.fetchone()
    rate = pay_row[0] if pay_row else 0.0

    # Najdeme najvyššie percento podľa rolí, ktoré hráč má
    user_role_ids = [role.id for role in hrac.roles]
    percent = 100.0  # Výchozie percento (100%)
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

    # Výpočet výplaty
    hours = total_seconds / 3600
    base_pay = hours * rate
    final_pay = base_pay * (percent / 100.0)

    embed = discord.Embed(title=f"Výplata zamestnanca: {hrac.display_name}", color=discord.Color.green())
    embed.add_field(name="Odpracovaný čas", value=f"{int(hours)} hod. {int((total_seconds % 3600) // 60)} min.", inline=False)
    embed.add_field(name="Základná mzda", value=f"{rate:.2f} €/hod", inline=False)
    embed.add_field(name="Aplikovaná rola / Kategória", value=f"{applied_role_name} ({percent}%)", inline=False)
    embed.add_field(name="Celková výplata", value=f"**{final_pay:.2f} €**", inline=False)
    
    await interaction.response.send_message(embed=embed)

bot.run("TVOJM_BOT_TOKEN")
        user_id INTEGER,
        kategoria TEXT,
        suma REAL
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS percenta (
        kategoria TEXT PRIMARY KEY,
        percento REAL
    )
''')

# Predvolené percentá pre kategórie
kategorie_default = {"oprava": 50.0, "tuning": 50.0, "DOT": 50.0, "odtah": 50.0}
for kat, perc in kategorie_default.items():
    cursor.execute("INSERT OR IGNORE INTO percenta (kategoria, percento) VALUES (?, ?)", (kat, perc))

conn.commit()


# ==========================================
# 1. ŠTRUKTÚRA PRE AKTIVITU (Tlačidlá a logika)
# ==========================================

class AktivitaView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Začať aktivitu", style=discord.ButtonStyle.green, custom_id="start_akt")
    async def start(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        cursor.execute("SELECT start_time FROM aktivity WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()

        if res:
            await interaction.response.send_message("❌ Už máš spustenú aktívnu službu!", ephemeral=True)
            return

        cursor.execute("INSERT INTO aktivity (user_id, start_time) VALUES (?, ?)", (user_id, time.time()))
        conn.commit()
        await interaction.response.send_message("🟢 Začal si merať aktivitu.", ephemeral=True)

    @discord.ui.button(label="Ukončiť aktivitu", style=discord.ButtonStyle.red, custom_id="stop_akt")
    async def stop(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        cursor.execute("SELECT start_time FROM aktivity WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()

        if not res:
            await interaction.response.send_message("❌ Nemáš spustenú žiadnu aktivitu!", ephemeral=True)
            return

        start_time = res[0]
        trvanie = time.time() - start_time

        cursor.execute("DELETE FROM aktivity WHERE user_id = ?", (user_id,))
        cursor.execute("INSERT INTO celkova_aktivita (user_id, sekundy) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET sekundy = sekundy + ?", (user_id, trvanie, trvanie))
        conn.commit()

        minuty = int(trvanie // 60)
        await interaction.response.send_message(f"🔴 Aktivita ukončená. Prirátaných **{minuty}** minút.", ephemeral=True)


# ==========================================
# 2. ŠTRUKTÚRA PRE FAKTÚRY (Menu a formulár)
# ==========================================

class FakturaSumaModal(Modal, title="Vytvorenie Faktúry"):
    def __init__(self, kategoria: str):
        super().__init__()
        self.kategoria = kategoria
        self.suma_input = TextInput(label=f"Suma pre {kategoria.capitalize()} ($)", placeholder="Zadaj sumu...", required=True)
        self.add_item(self.suma_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            suma = float(self.suma_input.value)
            if suma <= 0:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message("❌ Prosím, zadaj platné číslo!", ephemeral=True)
            return

        cursor.execute("INSERT INTO faktury (user_id, kategoria, suma) VALUES (?, ?, ?)", (interaction.user.id, self.kategoria, suma))
        conn.commit()
        await interaction.response.send_message(f"✅ Faktúra pre **{self.kategoria}** v hodnote **${suma:,.2f}** bola zaznamenaná.", ephemeral=True)


class FakturaSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Oprava", value="oprava", emoji="🔧"),
            discord.SelectOption(label="Tuning", value="tuning", emoji="🏎️"),
            discord.SelectOption(label="DOT", value="DOT", emoji="🚧"),
            discord.SelectOption(label="Odtah", value="odtah", emoji="🛞"),
        ]
        super().__init__(placeholder="Vyber druh faktúry...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(FakturaSumaModal(self.values[0]))


class FakturaView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Vytvoriť faktúru", style=discord.ButtonStyle.blurple, custom_id="create_faktura")
    async def create(self, interaction: discord.Interaction, button: Button):
        view = View()
        view.add_item(FakturaSelect())
        await interaction.response.send_message("Vyber druh faktúry:", view=view, ephemeral=True)


# ==========================================
# 3. NASTAVENIE PERCENT ADMINOM
# ==========================================

class PercentaModal(Modal, title="Úprava Percent Výplat"):
    oprava = TextInput(label="Oprava (%)", placeholder="napr. 50")
    tuning = TextInput(label="Tuning (%)", placeholder="napr. 50")
    dot = TextInput(label="DOT (%)", placeholder="napr. 50")
    odtah = TextInput(label="Odtah (%)", placeholder="napr. 50")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            vals = {
                "oprava": float(self.oprava.value),
                "tuning": float(self.tuning.value),
                "DOT": float(self.dot.value),
                "odtah": float(self.odtah.value)
            }
        except ValueError:
            await interaction.response.send_message("❌ Zadané hodnoty musia byť čísla!", ephemeral=True)
            return

        for k, v in vals.items():
            cursor.execute("UPDATE percenta SET percento = ? WHERE kategoria = ?", (v, k))
        conn.commit()

        await interaction.response.send_message("✅ Percentá výplat boli úspešne upravené!", ephemeral=True)


# ==========================================
# 4. PRÍKAZY BOTA (Slash Commands)
# ==========================================

# --- SETUP PRÍKAZY ---
@bot.tree.command(name="setup", description="Odošle správu s tlačidlami pre aktivitu")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(title="⏱️ Meranie Aktivity", description="Kliknutím na tlačidlo nižšie začneš alebo ukončíš svoju službu.", color=discord.Color.green())
    await interaction.channel.send(embed=embed, view=AktivitaView())
    await interaction.response.send_message("Panel aktivity bol vytvorený.", ephemeral=True)

@bot.tree.command(name="setup2", description="Odošle správu s tlačidlom pre faktúry")
@app_commands.checks.has_permissions(administrator=True)
async def setup2(interaction: discord.Interaction):
    embed = discord.Embed(title="📄 Evidencia Faktúr", description="Kliknutím na tlačidlo vytvoríš novú faktúru.", color=discord.Color.blue())
    await interaction.channel.send(embed=embed, view=FakturaView())
    await interaction.response.send_message("Panel faktúr bol vytvorený.", ephemeral=True)

@bot.tree.command(name="upravitper", description="Nastaví percentá z faktúr pre výplaty")
@app_commands.checks.has_permissions(administrator=True)
async def upravitper(interaction: discord.Interaction):
    await interaction.response.send_modal(PercentaModal())

# --- KONTROLA AKTIVITY ---
@bot.tree.command(name="aktivitacheck", description="Zobrazí aktivitu všetkých hráčov")
@app_commands.checks.has_permissions(administrator=True)
async def aktivitacheck(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, sekundy FROM celkova_aktivita")
    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message("Žiadne záznamy o aktivite.", ephemeral=True)
        return

    msg = "**📊 Aktivita všetkých hráčov:**\n"
    for uid, sek in rows:
        hodiny = round(sek / 3600, 2)
        msg += f"<@{uid}>: **{hodiny}** hodín\n"

    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="aktivitacheck1", description="Zobrazí aktivitu konkrétneho hráča")
async def aktivitacheck1(interaction: discord.Interaction, hrac: discord.User):
    cursor.execute("SELECT sekundy FROM celkova_aktivita WHERE user_id = ?", (hrac.id,))
    res = cursor.fetchone()
    hodiny = round(res[0] / 3600, 2) if res else 0.0
    await interaction.response.send_message(f"👤 Hráč {hrac.mention} má odpracované: **{hodiny}** hodín.", ephemeral=True)

@bot.tree.command(name="vymazataktivitu", description="Vymaže aktivitu pre jedného alebo všetkých")
@app_commands.checks.has_permissions(administrator=True)
async def vymazataktivitu(interaction: discord.Interaction, hrac: discord.User = None):
    if hrac:
        cursor.execute("DELETE FROM celkova_aktivita WHERE user_id = ?", (hrac.id,))
        await interaction.response.send_message(f"🗑️ Aktivita pre {hrac.mention} bola vymazaná.", ephemeral=True)
    else:
        cursor.execute("DELETE FROM celkova_aktivita")
        await interaction.response.send_message("🗑️ Aktivita **všetkých hráčov** bola vymazaná.", ephemeral=True)
    conn.commit()

# --- KONTROLA FAKTÚR ---
@bot.tree.command(name="fakturycheck", description="Zobrazí sumu faktúr všetkých hráčov")
@app_commands.checks.has_permissions(administrator=True)
async def fakturycheck(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, SUM(suma) FROM faktury GROUP BY user_id")
    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message("Žiadne evidované faktúry.", ephemeral=True)
        return

    msg = "**📑 Celkové faktúry hráčov:**\n"
    for uid, celkom in rows:
        msg += f"<@{uid}>: **${celkom:,.2f}**\n"

    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="fakturycheck1", description="Zobrazí sumu faktúr konkrétneho hráča")
async def fakturycheck1(interaction: discord.Interaction, hrac: discord.User):
    cursor.execute("SELECT SUM(suma) FROM faktury WHERE user_id = ?", (hrac.id,))
    res = cursor.fetchone()
    celkom = res[0] if res and res[0] else 0.0
    await interaction.response.send_message(f"👤 Hráč {hrac.mention} vytvoril faktúry v hodnote: **${celkom:,.2f}**.", ephemeral=True)

@bot.tree.command(name="vymazatfaktury", description="Vymaže faktúry pre jedného alebo všetkých")
@app_commands.checks.has_permissions(administrator=True)
async def vymazatfaktury(interaction: discord.Interaction, hrac: discord.User = None):
    if hrac:
        cursor.execute("DELETE FROM faktury WHERE user_id = ?", (hrac.id,))
        await interaction.response.send_message(f"🗑️ Faktúry pre {hrac.mention} boli vymazané.", ephemeral=True)
    else:
        cursor.execute("DELETE FROM faktury")
        await interaction.response.send_message("🗑️ Faktúry **všetkých hráčov** boli vymazané.", ephemeral=True)
    conn.commit()

# --- VÝPOČET VÝPLATY ---
@bot.tree.command(name="vyplata", description="Vypočíta tvoju aktuálnu výplatu z faktúr")
async def vyplata(interaction: discord.Interaction):
    user_id = interaction.user.id
    
    cursor.execute("SELECT percento, kategoria FROM percenta")
    perc_data = {kat: perc for perc, kat in cursor.fetchall()}

    cursor.execute("SELECT kategoria, SUM(suma) FROM faktury WHERE user_id = ? GROUP BY kategoria", (user_id,))
    faktury_data = cursor.fetchall()

    if not faktury_data:
        await interaction.response.send_message("Nemáš žiadne faktúry na preplatenie.", ephemeral=True)
        return

    celkova_vyplata = 0
    detail = ""

    for kat, suma in faktury_data:
        p = perc_data.get(kat, 0.0)
        zarobok = suma * (p / 100.0)
        celkova_vyplata += zarobok
        detail += f"• **{kat.capitalize()}**: ${suma:,.2f} (Sazba {p}%) ➡️ **${zarobok:,.2f}**\n"

    embed = discord.Embed(title=f"💰 Výplata pre {interaction.user.display_name}", color=discord.Color.gold())
    embed.add_field(name="Rozpis kategórií", value=detail, inline=False)
    embed.add_field(name="Celková výplata k vyplateniu", value=f"**${celkova_vyplata:,.2f}**", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- SPUSTENIE BOTA ---
@bot.event
async def on_ready():
    bot.add_view(AktivitaView())
    bot.add_view(FakturaView())
    await bot.tree.sync()
    print(f"Bot {bot.user} je online a synchronizovaný!")

bot.run(os.getenv('DISCORD_TOKEN'))

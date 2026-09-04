import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime
import os

# ---------------------------------------------------------
# BOT SETUP & CONFIGURATION
# ---------------------------------------------------------
# Načítanie tokenu z prostredia na začiatku kódu
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------
conn = sqlite3.connect("databaza.db")
cursor = conn.cursor()

# Tabuľka pre aktivitu
cursor.execute("""
CREATE TABLE IF NOT EXISTS activity (
    user_id INTEGER PRIMARY KEY,
    start_time TEXT,
    total_time INTEGER DEFAULT 0
)
""")

# Tabuľka pre faktúry
cursor.execute("""
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    amount REAL,
    created_at TEXT
)
""")

# Tabuľka pre percentuálne nastavenie ról pre výplaty
cursor.execute("""
CREATE TABLE IF NOT EXISTS role_percentages (
    role_id INTEGER PRIMARY KEY,
    tuning REAL DEFAULT 0.0,
    oprava REAL DEFAULT 0.0,
    dot REAL DEFAULT 0.0,
    odtah REAL DEFAULT 0.0
)
""")
conn.commit()

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def format_seconds(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}h {minutes}m {secs}s"

# ---------------------------------------------------------
# UI COMPONENTS (BUTTONS, MODALS & VIEWS)
# ---------------------------------------------------------

# 1. VIEW PRE AKTIVITU (/setup)
class ActivityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Začať prácu", style=discord.ButtonStyle.success, custom_id="start_act", emoji="▶️")
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
            title="✅ Práca začatá",
            description=f"Začal si pracovať o <t:{int(datetime.datetime.now().timestamp())}:T>.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Skončiť prácu", style=discord.ButtonStyle.danger, custom_id="stop_act", emoji="⏹️")
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
        
        embed = discord.Embed(
            title="🛑 Práca ukončená",
            description=f"Trvanie relácie: **{format_seconds(duration)}**.\nCelkovo odpracované: **{format_seconds(new_total)}**.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# 2. MODAL PRE ZADANIE SUMY FAKTÚRY
class InvoiceModal(discord.ui.Modal):
    def __init__(self, category: str):
        super().__init__(title=f"Vytvoriť faktúru - {category.upper()}")
        self.category = category

        self.amount_input = discord.ui.TextInput(
            label="Výška faktúry v €",
            placeholder="Napríklad 500",
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(self.amount_input.value.replace(',', '.'))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Zadaj platné číslo vyššie ako 0!", ephemeral=True)
            return

        now_str = datetime.datetime.now().isoformat()
        cursor.execute("INSERT INTO invoices (user_id, category, amount, created_at) VALUES (?, ?, ?, ?)",
                       (interaction.user.id, self.category, amount, now_str))
        conn.commit()

        embed = discord.Embed(
            title="🧾 Faktúra uložená",
            description=f"Kategória: **{self.category.capitalize()}**\nSuma: **{amount:.2f} €**",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# 3. SELECT MENU A VIEW PRE FAKTÚRY (/setup2)
class InvoiceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Tuning", value="tuning", emoji="🔧"),
            discord.SelectOption(label="Oprava", value="oprava", emoji="🛠️"),
            discord.SelectOption(label="DOT", value="dot", emoji="📋"),
            discord.SelectOption(label="Odtah", value="odtah", emoji="🚛"),
        ]
        super().__init__(placeholder="Vyber kategóriu faktúry...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        await interaction.response.send_modal(InvoiceModal(category))

class InvoiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Faktúry", style=discord.ButtonStyle.primary, custom_id="invoice_btn", emoji="🧾")
    async def invoice_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View()
        view.add_item(InvoiceSelect())
        await interaction.response.send_message("Vyber kategóriu faktúry:", view=view, ephemeral=True)

# ---------------------------------------------------------
# BOT EVENTS
# ---------------------------------------------------------
@bot.event
async def on_ready():
    bot.add_view(ActivityView())
    bot.add_view(InvoiceView())
    try:
        synced = await bot.tree.sync()
        print(f"Synchronizovaných {len(synced)} aplikovaných (slash) príkazov.")
    except Exception as e:
        print(f"Chyba pri synchronizácii príkazov: {e}")
        
    print(f"Bot {bot.user} je plne online a pripravený!")

# ---------------------------------------------------------
# SLASH COMMANDS
# ---------------------------------------------------------

# --- AKTIVITA PRÍKAZY ---

@bot.tree.command(name="setup", description="Odošle panel pre správu aktivity (začať/skončiť prácu)")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💼 Systém Sledovania Aktivity",
        description="Kliknutím na tlačidlá nižšie spravuješ svoj odpracovaný čas v službe.\n\n"
                    "▶️ **Začať prácu:** Spustí počítanie času.\n"
                    "⏹️ **Skončiť prácu:** Zastaví počítanie a pripočíta čas do databázy.",
        color=discord.Color.dark_blue()
    )
    await interaction.channel.send(embed=embed, view=ActivityView())
    await interaction.response.send_message("Panel pre aktivitu bol odoslaný!", ephemeral=True)

@bot.tree.command(name="mojaaktivita", description="Zobrazí tvoju odpracovanú aktivitu")
async def mojaaktivita(interaction: discord.Interaction):
    cursor.execute("SELECT start_time, total_time FROM activity WHERE user_id = ?", (interaction.user.id,))
    row = cursor.fetchone()
    
    total = row[1] if row and row[1] else 0
    if row and row[0]:
        start = datetime.datetime.fromisoformat(row[0])
        total += int((datetime.datetime.now() - start).total_seconds())

    embed = discord.Embed(
        title=f"📊 Aktivita používateľa {interaction.user.display_name}",
        description=f"Celkový odpracovaný čas: **{format_seconds(total)}**",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="aktivitazam", description="Zobrazí aktivitu všetkých zamestnancov")
@app_commands.checks.has_permissions(administrator=True)
async def aktivitazam(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, start_time, total_time FROM activity")
    rows = cursor.fetchall()
    
    if not rows:
        await interaction.response.send_message("Žiadne záznamy o aktivite.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 Aktivita všetkých zamestnancov", color=discord.Color.blue())
    for u_id, start_str, total in rows:
        user = interaction.guild.get_member(u_id)
        name = user.display_name if user else f"ID: {u_id}"
        t = total or 0
        if start_str:
            t += int((datetime.datetime.now() - datetime.datetime.fromisoformat(start_str)).total_seconds())
        embed.add_field(name=name, value=format_seconds(t), inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="aktivitazam1", description="Zobrazí aktivitu konkrétneho zamestnanca")
@app_commands.checks.has_permissions(administrator=True)
async def aktivitazam1(interaction: discord.Interaction, meno: discord.Member):
    cursor.execute("SELECT start_time, total_time FROM activity WHERE user_id = ?", (meno.id,))
    row = cursor.fetchone()
    
    total = row[1] if row and row[1] else 0
    if row and row[0]:
        total += int((datetime.datetime.now() - datetime.datetime.fromisoformat(row[0])).total_seconds())

    embed = discord.Embed(
        title=f"📊 Aktivita - {meno.display_name}",
        description=f"Odpracovaný čas: **{format_seconds(total)}**",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="zmazataktivita", description="Odobere zamestnancovi nastavený počet minút z aktivity")
@app_commands.checks.has_permissions(administrator=True)
async def zmazataktivita(interaction: discord.Interaction, meno: discord.Member, minute: int):
    cursor.execute("SELECT total_time FROM activity WHERE user_id = ?", (meno.id,))
    row = cursor.fetchone()
    
    if not row:
        await interaction.response.send_message("Používateľ nemá žiadne záznamy.", ephemeral=True)
        return

    new_total = max(0, (row[0] or 0) - (minute * 60))
    cursor.execute("UPDATE activity SET total_time = ? WHERE user_id = ?", (new_total, meno.id))
    conn.commit()

    await interaction.response.send_message(f"Používateľovi {meno.mention} bolo odebraných {minute} minút. Nový čas: **{format_seconds(new_total)}**", ephemeral=True)

@bot.tree.command(name="resetaktivita", description="Odstráni odpracované hodiny všetkým zamestnancom")
@app_commands.checks.has_permissions(administrator=True)
async def resetaktivita(interaction: discord.Interaction):
    cursor.execute("UPDATE activity SET total_time = 0, start_time = NULL")
    conn.commit()
    await interaction.response.send_message("Všetkým používateľom bola vymazaná aktivita!", ephemeral=True)


# --- PRIDANÉ: RESET VŠETKÝCH FAKTÚR ---

@bot.tree.command(name="reset", description="Vymaže všetky vystavené faktúry")
@app_commands.checks.has_permissions(administrator=True)
async def reset(interaction: discord.Interaction):
    cursor.execute("DELETE FROM invoices")
    conn.commit()

    await interaction.response.send_message(
        "🗑️ Všetky faktúry boli úspešne vymazané!",
        ephemeral=True
    )


# --- FAKTÚRY A VÝPLATY PRÍKAZY ---

@bot.tree.command(name="setup2", description="Odošle panel pre vystavovanie faktúr")
@app_commands.checks.has_permissions(administrator=True)
async def setup2(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🧾 Systém Faktúr",
        description="Klikni na tlačidlo nižšie pre výber kategórie a vystavenie faktúry.",
        color=discord.Color.gold()
    )
    await interaction.channel.send(embed=embed, view=InvoiceView())
    await interaction.response.send_message("Panel pre faktúry bol odoslaný!", ephemeral=True)

@bot.tree.command(name="fakturyzam", description="Zobrazí všetky vystavené faktúry")
@app_commands.checks.has_permissions(administrator=True)
async def fakturyzam(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, category, amount FROM invoices ORDER BY id DESC LIMIT 25")
    rows = cursor.fetchall()
    
    if not rows:
        await interaction.response.send_message("Nenašli sa žiadne faktúry.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 Všetky faktúry (posledných 25)", color=discord.Color.gold())
    for u_id, cat, amt in rows:
        user = interaction.guild.get_member(u_id)
        name = user.display_name if user else f"ID: {u_id}"
        embed.add_field(name=f"{name} - {cat.capitalize()}", value=f"{amt:.2f} €", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="fakturyzam1", description="Zobrazí faktúry konkrétneho zamestnanca")
@app_commands.checks.has_permissions(administrator=True)
async def fakturyzam1(interaction: discord.Interaction, meno: discord.Member):
    cursor.execute("SELECT category, amount FROM invoices WHERE user_id = ?", (meno.id,))
    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message(f"Používateľ {meno.display_name} nemá žiadne faktúry.", ephemeral=True)
        return

    embed = discord.Embed(title=f"🧾 Faktúry - {meno.display_name}", color=discord.Color.gold())
    total = 0
    for cat, amt in rows:
        embed.add_field(name=cat.capitalize(), value=f"{amt:.2f} €", inline=True)
        total += amt
    embed.description = f"Celkový súčet faktúr: **{total:.2f} €**"

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vyplataper", description="Nastaví percentuálnu časť výplaty z kategórií pre konkrétnu rolu")
@app_commands.checks.has_permissions(administrator=True)
async def vyplataper(interaction: discord.Interaction, rola: discord.Role, tuning: float, oprava: float, dot: float, odtah: float):
    cursor.execute("""
    INSERT OR REPLACE INTO role_percentages (role_id, tuning, oprava, dot, odtah)
    VALUES (?, ?, ?, ?, ?)
    """, (rola.id, tuning, oprava, dot, odtah))
    conn.commit()

    embed = discord.Embed(
        title="📊 Percentá Role Nastavené",
        description=f"Pre rolu {rola.mention} boli nastavené percentá:\n"
                    f"• **Tuning:** {tuning}%\n"
                    f"• **Oprava:** {oprava}%\n"
                    f"• **DOT:** {dot}%\n"
                    f"• **Odtah:** {odtah}%",
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Pomocná funkcia pre výpočet výplaty jedného zamestnanca
def compute_payroll(member: discord.Member):
    cursor.execute("SELECT category, SUM(amount) FROM invoices WHERE user_id = ? GROUP BY category", (member.id,))
    inv_rows = cursor.fetchall()
    totals = {cat: 0.0 for cat in ['tuning', 'oprava', 'dot', 'odtah']}
    for cat, sum_amt in inv_rows:
        if cat in totals:
            totals[cat] = sum_amt or 0.0

    # Vyhľadanie najlepšieho percenta z používateľových ról
    user_role_ids = [r.id for r in member.roles]
    percents = {'tuning': 0.0, 'oprava': 0.0, 'dot': 0.0, 'odtah': 0.0}

    if user_role_ids:
        placeholders = ','.join('?' for _ in user_role_ids)
        cursor.execute(f"SELECT tuning, oprava, dot, odtah FROM role_percentages WHERE role_id IN ({placeholders})", user_role_ids)
        roles_data = cursor.fetchall()
        for r_tun, r_opr, r_dot, r_odt in roles_data:
            percents['tuning'] = max(percents['tuning'], r_tun)
            percents['oprava'] = max(percents['oprava'], r_opr)
            percents['dot'] = max(percents['dot'], r_dot)
            percents['odtah'] = max(percents['odtah'], r_odt)

    total_payout = 0.0
    breakdown = []
    for cat in ['tuning', 'oprava', 'dot', 'odtah']:
        earned = totals[cat] * (percents[cat] / 100.0)
        total_payout += earned
        breakdown.append(f"• **{cat.capitalize()}**: Faktúry {totals[cat]:.2f} € ({percents[cat]}%) ➔ **{earned:.2f} €**")

    return total_payout, "\n".join(breakdown)

@bot.tree.command(name="vyplata", description="Zobrazí predbežný výpočet tvojej výplaty")
async def vyplata(interaction: discord.Interaction):
    total, breakdown = compute_payroll(interaction.user)
    embed = discord.Embed(
        title=f"💳 Výplata pre {interaction.user.display_name}",
        description=f"{breakdown}\n\n**Celková výplata: {total:.2f} €**",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vyplatazam", description="Zobrazí výplatu všetkých zamestnancov")
@app_commands.checks.has_permissions(administrator=True)
async def vyplatazam(interaction: discord.Interaction):
    cursor.execute("SELECT DISTINCT user_id FROM invoices")
    users = cursor.fetchall()

    if not users:
        await interaction.response.send_message("Žiadne faktúry pre výpočet výplat.", ephemeral=True)
        return

    embed = discord.Embed(title="💳 Výplaty všetkých zamestnancov", color=discord.Color.green())
    for (u_id,) in users:
        member = interaction.guild.get_member(u_id)
        if member:
            total, _ = compute_payroll(member)
            embed.add_field(name=member.display_name, value=f"**{total:.2f} €**", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vyplatazam1", description="Zobrazí výplatu konkrétneho zamestnanca")
@app_commands.checks.has_permissions(administrator=True)
async def vyplatazam1(interaction: discord.Interaction, meno: discord.Member):
    total, breakdown = compute_payroll(meno)
    embed = discord.Embed(
        title=f"💳 Výplata pre {meno.display_name}",
        description=f"{breakdown}\n\n**Celková výplata: {total:.2f} €**",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------------------------------------------------
# RUN BOT VIA ENVIRONMENT VARIABLE
# ---------------------------------------------------------
# Spustenie bota pomocou premennej TOKEN načítanej na začiatku
bot.run(TOKEN)

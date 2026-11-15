import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
import datetime
from dotenv import load_dotenv

load_dotenv()

# ====================== КОНФИГ ======================
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID', '0'))
LOBBY_CHANNEL_ID = int(os.getenv('LOBBY_CHANNEL_ID', '0'))
REVIEW_CHANNEL_ID = int(os.getenv('REVIEW_CHANNEL_ID', '0'))
HIGH_STAFF_ROLE_ID = int(os.getenv('HIGH_STAFF_ROLE_ID', '0'))
CITIZEN_ROLE_ID = int(os.getenv('CITIZEN_ROLE_ID', '0'))
FORMIL_ROLE_ID = int(os.getenv('FORMIL_ROLE_ID', '0'))

LOG_CHANNEL_ID = 1571627451153391656
FIB_ROLE_ID = 1571627847628492902
GOV_ROLE_ID = 1571608684251844739
LSPD_ROLE_ID = 1571608819828789419
SAHP_ROLE_ID = 1571608774001688687

LAW_LINK = "https://kenichilive.github.io/-SAHP/"

NICKS_FILE = "nicks.json"
STATS_FILE = "stats.json"
PENDING_FILE = "pending.json"

FACTIONS = {
    "FIB": FIB_ROLE_ID,
    "GOV": GOV_ROLE_ID,
    "LSPD": LSPD_ROLE_ID,
    "SAHP": SAHP_ROLE_ID,
}

# ====================== ХРАНИЛИЩА ======================
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Не удалось сохранить {path}: {e}")

nicks_db = load_json(NICKS_FILE, {})
stats_db = load_json(STATS_FILE, [])
pending_db = load_json(PENDING_FILE, {})

# ====================== ТЕКСТ СООБЩЕНИЯ ======================
LOBBY_TEXT = (
    "**📋 Заявка на вступление в семью «Атлантис»**\n\n"
    "Нажмите кнопку ниже, чтобы подать заявку.\n\n"
    f"**📖 Законодательство штата:** {LAW_LINK}"
)

# ====================== БОТ И КЛАССЫ ======================
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(LobbyView())
        self.add_view(ReviewView())
        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        else:
            await self.tree.sync()
        self.lobby_loop.start()
        self.reminder_loop.start()

    @tasks.loop(minutes=3)
    async def lobby_loop(self):
        await self.wait_until_ready()
        await self.ensure_lobby_message()

    async def ensure_lobby_message(self):
        guild = self.get_guild(GUILD_ID)
        if guild is None:
            return
        lobby = guild.get_channel(LOBBY_CHANNEL_ID)
        if lobby is None:
            return
        async for msg in lobby.history(limit=50):
            if msg.author.id != self.user.id:
                continue
            for row in msg.components:
                for child in row.children:
                    if getattr(child, "custom_id", None) == "lobby_apply":
                        if msg.embeds and LOBBY_TEXT not in (msg.embeds[0].description or ""):
                            embed = discord.Embed(title="📋 Заявка на вступление",
                                                  description=LOBBY_TEXT, color=discord.Color.gold())
                            await msg.edit(embed=embed, view=LobbyView())
                        return
        embed = discord.Embed(title="📋 Заявка на вступление",
                              description=LOBBY_TEXT, color=discord.Color.gold())
        await lobby.send(embed=embed, view=LobbyView())

    @tasks.loop(hours=1)
    async def reminder_loop(self):
        await self.wait_until_ready()
        guild = self.get_guild(GUILD_ID)
        if guild is None:
            return
        review = guild.get_channel(REVIEW_CHANNEL_ID)
        if review is None:
            return
        now = datetime.datetime.utcnow()
        for tid, info in list(pending_db.items()):
            if info.get("reminded"):
                continue
            created = datetime.datetime.fromisoformat(info["created"])
            if (now - created).total_seconds() < 24 * 3600:
                continue
            thread = guild.get_thread(int(tid))
            if thread is None:
                continue
            member = guild.get_member(info["user_id"])
            if member:
                hs = guild.get_role(HIGH_STAFF_ROLE_ID)
                await review.send(
                    f"⏰ {hs.mention if hs else '@High Staff'} заявка от {member.mention} висит более 24 часов!"
                )
                info["reminded"] = True
                save_json(PENDING_FILE, pending_db)

# Создаем объект бота ДО декораторов
bot = MyBot()

# ====================== КЛАССЫ UI ======================
class ApplicationModal(discord.ui.Modal, title="Заявка на вступление"):
    static_id = discord.ui.TextInput(label="Static ID", placeholder="Например: 27304", max_length=30)
    nickname = discord.ui.TextInput(label="Никнейм (без фракции)", placeholder="Например: Ken Atlantis", max_length=50)
    knowledge = discord.ui.TextInput(
        label="Знание законодательной базы",
        style=discord.TextStyle.paragraph,
        placeholder="Кратко опишите, что знаете",
        max_length=1000
    )

    def __init__(self):
        super().__init__()
        self.faction = discord.ui.Select(
            placeholder="Фракция (необязательно)",
            options=[discord.SelectOption(label=f, value=f) for f in FACTIONS.keys()],
            min_values=0, max_values=1, required=False,
        )
        self.add_item(self.faction)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        for tid, info in pending_db.items():
            if info.get("user_id") == interaction.user.id:
                thread = guild.get_thread(int(tid))
                link = thread.mention if thread else "ваша заявка"
                await interaction.response.send_message(
                    f"❌ У вас уже есть активная заявка: {link}", ephemeral=True
                )
                return

        nick_key = self.nickname.value.strip().lower()
        if nick_key in nicks_db and nicks_db[nick_key] != interaction.user.id:
            await interaction.response.send_message(
                f"❌ Ник `{self.nickname.value}` уже занят в семье. Выберите другой.",
                ephemeral=True,
            )
            return

        lobby = guild.get_channel(LOBBY_CHANNEL_ID)
        if lobby is None:
            await interaction.response.send_message("❌ Канал прихожей не найден.", ephemeral=True)
            return

        thread = await lobby.create_thread(
            name=f"Заявка · {interaction.user.display_name}",
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=60,
        )
        await thread.add_user(interaction.user)

        high_staff = guild.get_role(HIGH_STAFF_ROLE_ID)
        if high_staff:
            for member in high_staff.members:
                try:
                    await thread.add_user(member)
                except Exception:
                    pass

        pending_db[str(thread.id)] = {
            "user_id": interaction.user.id,
            "created": datetime.datetime.utcnow().isoformat(),
            "reminded": False,
            "data": {
                "static_id": self.static_id.value,
                "nickname": self.nickname.value,
                "faction": self.faction.values[0] if self.faction.values else "",
                "knowledge": self.knowledge.value,
            },
        }
        save_json(PENDING_FILE, pending_db)

        await interaction.response.send_message(
            f"✅ Заявка создана: {thread.mention}\n\n**Прикрепите скриншот документов** одним сообщением.",
            ephemeral=True,
        )
        await thread.send(
            f"{interaction.user.mention}, прикрепите **скриншот документов** одним сообщением. "
            f"После этого заявка автоматически уйдёт в High Staff."
        )

class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _parse(self, interaction):
        footer = interaction.message.embeds[0].footer.text
        parts = dict(p.split(":", 1) for p in footer.split("|"))
        user_id = int(parts["UserID"])
        faction = parts.get("Faction", "").strip()
        static = parts.get("Static", "").strip()
        nick = parts.get("Nick", "").strip()
        member = interaction.guild.get_member(user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except Exception:
                member = None
        return member, faction, static, nick

    async def _finalize(self, interaction, status_text, color, log_text):
        embed = interaction.message.embeds[0]
        embed.color = color
        embed.add_field(name="Статус", value=status_text, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)
        await self._log(interaction, log_text)

    async def _log(self, interaction, text):
        log = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log:
            await log.send(
                f"`{datetime.datetime.utcnow():%Y-%m-%d %H:%M} UTC` · "
                f"{interaction.user.mention} → {text}\n"
                f"Заявка: [перейти]({interaction.message.jump_url})"
            )
        stats_db.append({
            "action": text.split()[0],
            "user_id": interaction.message.embeds[0].footer.text.split("|")[0].replace("UserID:", ""),
            "by": interaction.user.id,
            "time": datetime.datetime.utcnow().isoformat(),
        })
        save_json(STATS_FILE, stats_db)

    @discord.ui.button(label="На рассмотрении", style=discord.ButtonStyle.secondary, custom_id="app_pending")
    async def pending(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"⏳ {interaction.user.mention} взял заявку в работу.", ephemeral=False
        )
        await self._log(interaction, "⏳ взял в работу")

    @discord.ui.button(label="Одобрить", style=discord.ButtonStyle.success, custom_id="app_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        member, faction, static, nick = await self._parse(interaction)
        if member is None:
            await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)
            return

        roles_to_add = []
        formil = interaction.guild.get_role(FORMIL_ROLE_ID)
        if formil:
            roles_to_add.append(formil)
        if faction and faction in FACTIONS:
            role = interaction.guild.get_role(FACTIONS[faction])
            if role:
                roles_to_add.append(role)

        if roles_to_add:
            await member.add_roles(*roles_to_add, reason="Заявка одобрена")

        new_nick = f"{faction} | {nick} | {static}" if faction else f"{nick} | {static}"
        try:
            await member.edit(nick=new_nick[:32])
        except Exception:
            pass

        nicks_db[nick.lower()] = member.id
        save_json(NICKS_FILE, nicks_db)

        try:
            await member.send(f"🎉 Ваша заявка одобрена! Ник изменён на `{new_nick}`.")
        except Exception:
            pass

        await self._finalize(
            interaction,
            f"✅ Одобрено ({interaction.user.mention})",
            discord.Color.green(),
            f"✅ Одобрил заявку {member.mention} (ник: `{new_nick}`)",
        )

    @discord.ui.button(label="Отклонить (кик)", style=discord.ButtonStyle.danger, custom_id="app_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        member, _, _, _ = await self._parse(interaction)
        try:
            if member:
                await member.send("❌ Ваша заявка отклонена.")
        except Exception:
            pass
        if member:
            try:
                await member.kick(reason="Заявка отклонена")
            except Exception as e:
                await interaction.response.send_message(f"⚠️ Не удалось кикнуть: {e}", ephemeral=True)
                return
        await self._finalize(
            interaction, f"❌ Отклонено и кикнут ({interaction.user.mention})",
            discord.Color.red(), f"❌ Отклонил и кикнул {member.mention if member else 'пользователя'}",
        )

    @discord.ui.button(label="Дать роль Гражданин", style=discord.ButtonStyle.primary, custom_id="app_citizen")
    async def citizen(self, interaction: discord.Interaction, button: discord.ui.Button):
        member, _, _, _ = await self._parse(interaction)
        if member is None:
            await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)
            return
        citizen = interaction.guild.get_role(CITIZEN_ROLE_ID)
        if citizen:
            await member.add_roles(citizen, reason="Гражданин по заявке")
        try:
            await member.send("✅ Вам выдана роль Гражданин.")
        except Exception:
            pass
        await self._finalize(
            interaction, f"🎖️ Гражданин выдан ({interaction.user.mention})",
            discord.Color.gold(), f"🎖️ Выдал Гражданин {member.mention}",
        )

class LobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Оставить заявку", style=discord.ButtonStyle.primary,
                       custom_id="lobby_apply", emoji="📝")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplicationModal())

# ====================== СОБЫТИЯ И КОМАНДЫ ======================
@bot.listen('on_message')
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    info = pending_db.get(str(message.channel.id))
    if not info:
        return
    if not message.attachments:
        return

    data = info["data"]
    screenshot = message.attachments[0]
    faction = data.get("faction") or "—"

    embed = discord.Embed(title="📋 Новая заявка", color=discord.Color.blurple())
    embed.add_field(name="Кандидат", value=f"<@{info['user_id']}>", inline=False)
    embed.add_field(name="Static ID", value=data["static_id"], inline=True)
    embed.add_field(name="Никнейм", value=data["nickname"], inline=True)
    embed.add_field(name="Фракция", value=faction, inline=True)
    embed.add_field(name="Знание законодательной базы", value=data["knowledge"][:1024], inline=False)
    embed.set_image(url=screenshot.url)
    embed.set_footer(
        text=f"UserID:{info['user_id']}|Faction:{faction}|Static:{data['static_id']}|Nick:{data['nickname']}"
    )

    review = message.guild.get_channel(REVIEW_CHANNEL_ID)
    if review:
        await review.send(embed=embed, view=ReviewView())

    del pending_db[str(message.channel.id)]
    save_json(PENDING_FILE, pending_db)

    await message.channel.send("✅ Заявка отправлена в High Staff. Тред закрывается.")
    await message.channel.edit(archived=True, locked=True)

@bot.tree.command(name="статистика", description="Статистика заявок за последние 7 дней")
@app_commands.checks.has_permissions(administrator=True)
async def stats_cmd(interaction: discord.Interaction):
    week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    recent = [s for s in stats_db if datetime.datetime.fromisoformat(s["time"]) >= week_ago]
    approved = sum(1 for s in recent if s["action"].startswith("✅"))
    rejected = sum(1 for s in recent if s["action"].startswith("❌"))
    citizens = sum(1 for s in recent if s["action"].startswith("🎖️"))
    pending_count = len(pending_db)
    embed = discord.Embed(title="📊 Статистика за 7 дней", color=discord.Color.blurple())
    embed.add_field(name="✅ Одобрено", value=str(approved))
    embed.add_field(name="❌ Отклонено", value=str(rejected))
    embed.add_field(name="🎖️ Граждан", value=str(citizens))
    embed.add_field(name="⏳ В ожидании", value=str(pending_count))
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ====================== ЗАПУСК ======================
if __name__ == "__main__":
    bot.run(TOKEN)
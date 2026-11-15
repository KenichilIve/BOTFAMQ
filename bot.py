import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import time
from dotenv import load_dotenv

load_dotenv()

# Токен берется из настроек хостинга
TOKEN = os.getenv('DISCORD_TOKEN') or os.getenv('DISCORD_BOT_TOKEN')
GUILD_ID = 1571596520631828481

# --- ID каналов и ролей ---
LOBBY_CATEGORY_ID = 1571609625281695936
APPLY_CHANNEL_ID = 1571610657357570088
REVIEW_CHANNEL_ID = 1571615608934768670
HIGH_STAFF_ROLE_ID = 1571608485953667264
FORMIL_ROLE_ID = 1571608561690349618
CITIZEN_ROLE_ID = 1571608643411906632
AFK_CHANNEL_ID = 1571613363065327647

pending_applications = {}
voice_activity = {}
AFK_TIMEOUT_SECONDS = 10 * 60

# ====================== СОЗДАЕМ БОТА ЗДЕСЬ ======================
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(LobbyView())
        self.add_view(ReviewView())
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        afk_checker.start()

bot = MyBot()

# ====================== ФОРМА ЗАЯВКИ ======================
class ApplicationModal(discord.ui.Modal, title="Заявка на вступление"):
    static_id = discord.ui.TextInput(label="Static ID", placeholder="Например: 12345", max_length=30)
    nickname = discord.ui.TextInput(label="Никнейм", placeholder="Ваш игровой ник", max_length=50)
    faction = discord.ui.TextInput(label="Фракция (если есть)", required=False,
                                   placeholder="Например: МВД (или оставьте пустым)", max_length=50)
    knowledge = discord.ui.TextInput(label="Знание законодательной базы", style=discord.TextStyle.paragraph,
                                     placeholder="Кратко опишите, что знаете", max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        lobby = guild.get_channel(APPLY_CHANNEL_ID)
        if lobby is None:
            await interaction.response.send_message("❌ Канал прихожей не найден.", ephemeral=True)
            return
        thread = await lobby.create_thread(
            name=f"Заявка · {interaction.user.display_name}",
            type=discord.ChannelType.private_thread, invitable=False, auto_archive_duration=60)
        await thread.add_user(interaction.user)
        high_staff = guild.get_role(HIGH_STAFF_ROLE_ID)
        if high_staff:
            for member in high_staff.members:
                try:
                    await thread.add_user(member)
                except Exception:
                    pass
        pending_applications[thread.id] = {
            'user_id': interaction.user.id, 'static_id': self.static_id.value,
            'nickname': self.nickname.value, 'faction': (self.faction.value or "").strip(),
            'knowledge': self.knowledge.value}
        await interaction.response.send_message(
            f"✅ Заявка создана: {thread.mention}\n\n**Прикрепите скриншот документов** одним сообщением в тред.",
            ephemeral=True)
        await thread.send(f"{interaction.user.mention}, прикрепите **скриншот документов** одним сообщением.")


# ====================== ПРОВЕРКА СКРИНШОТА ======================
@bot.listen('on_message')
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    if message.channel.id not in pending_applications:
        return
    if not message.attachments:
        return
    data = pending_applications[message.channel.id]
    screenshot = message.attachments[0]
    embed = discord.Embed(title="📋 Новая заявка", color=discord.Color.blurple())
    embed.add_field(name="Кандидат", value=f"<@{data['user_id']}>", inline=False)
    embed.add_field(name="Static ID", value=data['static_id'], inline=True)
    embed.add_field(name="Никнейм", value=data['nickname'], inline=True)
    embed.add_field(name="Фракция", value=data['faction'] or "—", inline=True)
    embed.add_field(name="Знание законодательной базы", value=data['knowledge'][:1024], inline=False)
    embed.set_image(url=screenshot.url)
    embed.set_footer(text=f"UserID:{data['user_id']}|Faction:{data['faction'] or '—'}")
    review = message.guild.get_channel(REVIEW_CHANNEL_ID)
    if review:
        await review.send(embed=embed, view=ReviewView())
    del pending_applications[message.channel.id]
    await message.channel.send("✅ Заявка отправлена в High Staff. Тред закрывается.")
    await message.channel.edit(archived=True, locked=True)


# ====================== КНОПКИ РАССМОТРЕНИЯ ======================
class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _get_member(self, interaction: discord.Interaction):
        footer = interaction.message.embeds[0].footer.text
        user_id = int(footer.split('|')[0].replace('UserID:', '').strip())
        faction = footer.split('|')[1].replace('Faction:', '').strip() if '|' in footer else ''
        member = interaction.guild.get_member(user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except Exception:
                member = None
        return member, faction

    async def _finalize(self, interaction, status_text, color):
        embed = interaction.message.embeds[0]
        embed.color = color
        embed.add_field(name="Статус", value=status_text, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Одобрить", style=discord.ButtonStyle.success, custom_id="app_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        member, faction = await self._get_member(interaction)
        if member is None:
            await interaction.response.send_message("❌ Пользователь не найден.", ephemeral=True)
            return
        roles_to_add, warn = [], ""
        formil = interaction.guild.get_role(FORMIL_ROLE_ID)
        if formil:
            roles_to_add.append(formil)
        if faction and faction != "—":
            faction_role = discord.utils.get(interaction.guild.roles, name=faction)
            if faction_role:
                roles_to_add.append(faction_role)
            else:
                warn = f"\n⚠️ Роль фракции `{faction}` не найдена — выдай вручную."
        if roles_to_add:
            await member.add_roles(*roles_to_add, reason="Заявка одобрена")
        try:
            await member.send("🎉 Ваша заявка одобрена! Добро пожаловать.")
        except Exception:
            pass
        await self._finalize(interaction, f"✅ Одобрено ({interaction.user.mention}){warn}", discord.Color.green())

    @discord.ui.button(label="Отклонить (кик)", style=discord.ButtonStyle.danger, custom_id="app_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        member, _ = await self._get_member(interaction)
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
        await self._finalize(interaction, f"❌ Отклонено и кикнут ({interaction.user.mention})", discord.Color.red())

    @discord.ui.button(label="Дать роль Гражданин", style=discord.ButtonStyle.primary, custom_id="app_citizen")
    async def citizen(self, interaction: discord.Interaction, button: discord.ui.Button):
        member, _ = await self._get_member(interaction)
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
        await self._finalize(interaction, f"🎖️ Гражданин выдан ({interaction.user.mention})", discord.Color.gold())


# ====================== КНОПКА В ПРИХОЖЕЙ ======================
class LobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Оставить заявку", style=discord.ButtonStyle.primary,
                       custom_id="lobby_apply", emoji="📝")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplicationModal())


# ====================== AFK ЧЕРЕЗ 10 МИНУТ ======================
@bot.listen('on_voice_state_update')
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    if after.channel and after.channel.id != AFK_CHANNEL_ID:
        voice_activity[member.id] = time.time()
    elif after.channel is None:
        voice_activity.pop(member.id, None)
    elif after.channel.id == AFK_CHANNEL_ID:
        voice_activity.pop(member.id, None)


@tasks.loop(seconds=30)
async def afk_checker():
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return
    afk_channel = guild.get_channel(AFK_CHANNEL_ID)
    if afk_channel is None:
        return
    now = time.time()
    for member_id, last_seen in list(voice_activity.items()):
        member = guild.get_member(member_id)
        if member is None or member.voice is None or member.voice.channel is None:
            voice_activity.pop(member_id, None)
            continue
        if member.voice.channel.id == AFK_CHANNEL_ID:
            voice_activity.pop(member_id, None)
            continue
        if now - last_seen >= AFK_TIMEOUT_SECONDS:
            try:
                await member.move_to(afk_channel, reason="AFK: 10 минут без активности")
                voice_activity.pop(member_id, None)
            except Exception:
                pass


# ====================== КОМАНДА РАЗМЕЩЕНИЯ КНОПКИ ======================
@bot.tree.command(name="разместить_кнопку", description="[Админ] Разместить кнопку заявки в прихожей")
@app_commands.checks.has_permissions(administrator=True)
async def place_button(interaction: discord.Interaction):
    lobby = interaction.guild.get_channel(APPLY_CHANNEL_ID)
    if lobby is None:
        await interaction.response.send_message("❌ Канал прихожей не найден.", ephemeral=True)
        return
    embed = discord.Embed(
        title="📋 Заявка на вступление",
        description=("Нажмите кнопку ниже, чтобы подать заявку.\n\n"
                     "**В форме укажите:**\n• Static ID\n• Никнейм\n• Фракцию (если есть)\n"
                     "• Знание законодательной базы\n\n"
                     "После отправки формы **прикрепите скриншот документов** в созданном треде."),
        color=discord.Color.gold())
    await lobby.send(embed=embed, view=LobbyView())
    await interaction.response.send_message("✅ Кнопка размещена.", ephemeral=True)


bot.run(TOKEN)
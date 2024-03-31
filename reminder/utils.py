import discord
from discord.ext import commands

from pie import i18n, utils

from .database import ReminderItem

_ = i18n.Translator("modules/reminder").translate


async def get_reminder_embed(
    bot: commands.Bot, itx: discord.Interaction, query: ReminderItem
):
    reminder_user = await get_member(bot, query.author_id, query.guild_id)

    if reminder_user is None:
        reminder_user_name = "_({unknown})_".format(unknown=_(itx, "Unknown user"))
    else:
        reminder_user_name = discord.utils.escape_markdown(reminder_user.display_name)

    embed = utils.discord.create_embed(
        author=reminder_user,
        title=_(itx, "Reminder"),
    )

    if query.author_id != query.recipient_id:
        embed.add_field(
            name=_(itx, "Reminded by"),
            value=reminder_user_name,
            inline=True,
        )
    if query.message != "":
        embed.add_field(
            name=_(itx, "Message"),
            value=query.message,
            inline=False,
        )
    if query.permalink:
        embed.add_field(name=_(itx, "URL"), value=query.permalink, inline=True)

    embed.add_field(
        name=_(itx, "Remind date"),
        value=utils.time.format_datetime(timestamp=query.remind_date),
        inline=False,
    )

    return embed


async def get_member(bot: commands.Bot, user_id: int, guild_id: int = 0):
    user = None

    if guild_id > 0:
        guild = bot.get_guild(guild_id)
        user = guild.get_member(user_id)

    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.errors.NotFound:
            pass

    return user

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import discord
from discord import app_commands
from discord.errors import Forbidden, HTTPException
from discord.ext import commands, tasks

from pie import check, i18n, logger, utils
from pie.utils.objects import ConfirmView

from .database import ReminderItem, ReminderStatus
from .objects import RemindModal
from .utils import get_member, get_reminder_embed

_ = i18n.Translator("modules/reminder").translate
bot_log = logger.Bot.logger()
guild_log = logger.Guild.logger()


class Reminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_loop.start()

        self.remindme_menu = app_commands.ContextMenu(
            name="Remind me", callback=self.remindme_menu_handler
        )

        self.bot.tree.add_command(self.remindme_menu)

    reminder = app_commands.Group(
        name="reminder", description="Reminder management commands."
    )

    def cog_unload(self):
        self.reminder_loop.cancel()

    # LOOPS

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        max_remind_time = datetime.now() + timedelta(seconds=30)

        items = ReminderItem.get_all(
            status=ReminderStatus.WAITING, max_remind_date=max_remind_time
        )

        if items is not None:
            for item in items:
                await self._remind(item)

    @reminder_loop.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

    # HELPER FUNCTIONS

    async def _remind(self, item: ReminderItem):
        reminded_user = await get_member(self.bot, item.recipient_id, item.guild_id)

        if reminded_user is None:
            item.status = ReminderStatus.FAILED
            item.save()
            await bot_log.warning(
                item.recipient_id,
                item.guild_id,
                "Unable to remind user - member out of bot's reach.",
            )
            return

        utx = i18n.TranslationContext(item.guild_id, item.recipient_id)

        embed = await get_reminder_embed(self.bot, utx, item)

        try:
            message = await reminded_user.send(embed=embed)
        except (HTTPException, Forbidden):
            item.status = ReminderStatus.FAILED
            item.save()
            await bot_log.warning(
                item.recipient_id,
                item.guild_id,
                "Unable to remind user - blocked PM or not enough permissions.",
            )
            return

        item.status = ReminderStatus.REMINDED
        item.save()

        await bot_log.debug(
            reminded_user,
            message.channel.id,
            "Reminder ID {id} succesfully sent to {user}".format(
                id=item.idx, user=reminded_user.display_name
            ),
        )

    async def _send_reminder_list(
        self, itx: discord.Interaction, query, *, include_reminded: bool = True
    ):
        reminders = []

        for item in query:
            author = await get_member(self.bot, item.author_id, item.guild_id)
            remind = await get_member(self.bot, item.recipient_id, item.guild_id)

            author_name = (
                author.display_name if author is not None else _(itx, "(unknown)")
            )
            remind_name = (
                remind.display_name if remind is not None else _(itx, "(unknown)")
            )

            reminder = ReminderDummy()
            reminder.idx = item.idx
            reminder.author_name = author_name
            reminder.remind_name = remind_name
            reminder.remind_date = item.remind_date.strftime("%Y-%m-%d %H:%M")
            reminder.status = item.status.name
            reminder.message = item.message

            if reminder.message and len(reminder.message) > 30:
                reminder.message = reminder.message[:29] + "\N{HORIZONTAL ELLIPSIS}"

            reminders.append(reminder)

        table_columns: dict = {
            "idx": _(itx, "ID"),
            "author_name": _(itx, "Author"),
            "remind_name": _(itx, "Reminded"),
            "remind_date": _(itx, "Remind date"),
            "status": _(itx, "Status"),
            "message": _(itx, "Message text"),
        }
        if not include_reminded:
            del table_columns["remind_name"]

        table_pages: List[str] = utils.text.create_table(reminders[::-1], table_columns)

        for table_page in table_pages:
            await itx.response.send_message(
                "```" + table_page.replace("`", "'") + "```", ephemeral=True
            )

    # CONTEXT MENU

    @check.acl2(check.ACLevel.EVERYONE)
    async def remindme_menu_handler(
        self, itx: discord.Interaction, message: discord.Message
    ):
        remind_modal = RemindModal(
            self.bot,
            title=_(itx, "Remind me this message"),
            label=_(itx, "Date / time:"),
            recipient=itx.user,
            message=message,
        )
        await itx.response.send_modal(remind_modal)

    # COMMANDS

    @check.acl2(check.ACLevel.EVERYONE)
    @app_commands.command(name="remindme")
    async def remindme(
        self,
        itx: discord.Interaction,
    ):
        """Create reminder for you."""
        remind_modal = RemindModal(
            self.bot,
            title=_(itx, "Remind me this message"),
            label=_(itx, "Date / time:"),
            recipient=itx.user,
        )
        await itx.response.send_modal(remind_modal)

    @check.acl2(check.ACLevel.MEMBER)
    @app_commands.guild_only()
    @app_commands.command(
        name="remind", description="Create reminder for another user."
    )
    @app_commands.describe(
        member="Member to remind.", message_url="Optional message URL to remind."
    )
    async def remind(
        self,
        itx: discord.Interaction,
        member: discord.Member,
        message_url: Optional[str] = None,
    ):
        message: discord.Message
        if message_url:
            split: Tuple[int, int, int] = utils.discord.split_message_url(
                self.bot, message_url
            )
            if not split:
                await itx.response.send_message(
                    _(itx, "Incorrect message URL!"), ephemeral=True
                )
                return
            guild_id, channel_id, message_id = split
            if guild_id != itx.guild.id:
                await itx.response.send_message(
                    _(
                        itx,
                        "The message must be on the same server as the reminded user!",
                    ),
                    ephemeral=True,
                )
                return

            message = await utils.discord.get_message(
                bot=self.bot,
                guild_or_user_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            if not message:
                await itx.response.send_message(
                    _(itx, "Message not found!"), ephemeral=True
                )
                return

        remind_modal = RemindModal(
            self.bot,
            title=_(itx, "Remind {member} this message").format(member=member.nick),
            label=_(itx, "Date / time:"),
            recipient=member,
            message=message,
        )
        await itx.response.send_modal(remind_modal)

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder.command(name="list", description="List reminders for you.")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="WAITING", value="WAITING"),
            app_commands.Choice(name="REMINDED", value="REMINDED"),
            app_commands.Choice(name="FAILED", value="FAILED"),
            app_commands.Choice(name="ALL", value="ALL"),
        ]
    )
    async def reminder_list(
        self, itx: discord.Interaction, status: app_commands.Choice[str]
    ):
        query: List[ReminderItem]

        if status.value == "ALL":
            query = ReminderItem.get_all(recipient=itx.user)
        else:
            try:
                rem_status: ReminderStatus = ReminderStatus[status.value]
            except KeyError:
                await itx.response.send_message(
                    _(itx, "Invalid status. Allowed: {status}").format(
                        status=ReminderStatus.str_list() + ", ALL"
                    ),
                    ephemeral=True,
                )
                return

            query = ReminderItem.get_all(recipient=itx.user, status=rem_status)

        await self._send_reminder_list(itx, query)

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder.command(name="info", description="Show reminder details.")
    async def reminder_info(self, itx: discord.Interaction, idx: int):
        query = ReminderItem.get_all(guild=itx.guild, idx=idx)
        if not query:
            await itx.response.send_message(
                _(itx, "Reminder with ID {id} does not exist.").format(id=idx),
                ephemeral=True,
            )
            return
        item = query[0]
        if itx.user.id not in (item.author_id, item.recipient_id):
            await itx.response.send_message(
                _(itx, "You don't have permission to see details of this reminder."),
                ephemeral=True,
            )
            return

        created_for: str = _(itx, "Created {timestamp}").format(
            timestamp=utils.time.format_datetime(item.origin_date)
        )
        if item.author_id != itx.user.id:
            item_author = itx.guild.get_member(item.author_id)
            created_for += " " + _(itx, "by {member}").format(
                member=getattr(item_author, "display_name", str(item.author_id))
            )
        else:
            created_for += " " + _(itx, "by you")
        scheduled_for: str = _(itx, "Scheduled for **{timestamp}**").format(
            timestamp=utils.time.format_datetime(item.remind_date)
        )
        if item.recipient_id != itx.user.id:
            item_recipient = itx.guild.get_member(item.recipient_id)
            scheduled_for += " " + _(itx, "for {member}").format(
                member=getattr(item_recipient, "display_name", str(item.recipient_id))
            )
        else:
            scheduled_for += " " + _(itx, "for you")

        embed = utils.discord.create_embed(
            author=itx.user,
            title=_(itx, "Reminder #{idx}").format(idx=idx),
            description=f"{created_for}\n{scheduled_for}",
        )
        embed.add_field(name=_(itx, "Content"), value=item.message, inline=False)
        embed.add_field(name=_(itx, "Status"), value=item.status.value)

        await itx.response.send_message(embed=embed, ephemeral=True)

    @app_commands.guild_only()
    @check.acl2(check.ACLevel.MOD)
    @reminder.command(name="all", description="List all guild reminders")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="WAITING", value="WAITING"),
            app_commands.Choice(name="REMINDED", value="REMINDED"),
            app_commands.Choice(name="FAILED", value="FAILED"),
            app_commands.Choice(name="ALL", value="ALL"),
        ]
    )
    async def reminder_app(
        self, itx: discord.Interaction, status: app_commands.Choice[str]
    ):
        query: List[ReminderItem]

        if status.value == "ALL":
            query = ReminderItem.get_all(guild=itx.guild)
        else:
            try:
                rem_status: ReminderStatus = ReminderStatus[status.value]
            except KeyError:
                await itx.response.send_message(
                    _(itx, "Invalid status. Allowed: {status}").format(
                        status=ReminderStatus.str_list() + ", ALL"
                    ),
                    ephemeral=True,
                )
                return

            query = ReminderItem.get_all(guild=itx.guild, status=rem_status)

        await self._send_reminder_list(itx, query)

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder.command(name="edit", description="Reschedule your reminder.")
    @app_commands.describe(
        idx="Reminder ID",
    )
    async def edit(self, itx: discord.Interaction, idx: int):
        query = ReminderItem.get_all(idx=idx)
        if query is None:
            await itx.response.send_message(
                _(itx, "Reminder with ID {id} does not exist.").format(id=idx),
                ephemeral=True,
            )
            return

        query = query[0]

        if query.recipient_id != itx.user.id:
            await itx.response.send_message(
                _(itx, "Can't reschedule other's reminders."), ephemeral=True
            )
            return

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder.command(name="delete", description="Delete reminder")
    @app_commands.describe(idx="Reminder ID")
    async def reminder_delete(self, itx: discord.Interaction, idx: int):
        query = ReminderItem.get_all(idx=idx)
        if not query:
            await itx.response.send_message(
                _(itx, "Reminder with ID {id} does not exist.").format(id=idx),
                ephemeral=True,
            )
            return

        query = query[0]

        if query.recipient_id != itx.user.id:
            await itx.response.send_message(
                _(itx, "Can't delete other's reminders."), ephemeral=True
            )
            return

        embed = await get_reminder_embed(self.bot, itx, query)
        embed.title = _(itx, "Do you want to delete this reminder?")
        view = ConfirmView(itx, embed)

        value = await view.send()
        if value is None:
            await itx.user.send(_(itx, "Deleting timed out."), ephemeral=True)
        elif value:
            query.delete()
            await view.itx.response.send_message(
                _(itx, "Reminder deleted."), ephemeral=True
            )
            await guild_log.debug(
                itx.user,
                itx.channel,
                f"Reminder #{idx} cancelled.",
            )
        else:
            await view.itx.response.send_message(
                _(itx, "Deleting aborted."), ephemeral=True
            )

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder.command(
        name="clean",
        description="Delete all your reminders that finished at least 24 hours ago.",
    )
    async def reminder_clean(self, itx: discord.Interaction):
        """"""
        before: datetime = datetime.now() - timedelta(hours=24)
        count: int = ReminderItem.batch_delete(itx.guild, itx.user, before)

        if not count:
            await itx.response.send_message(
                _(itx, "You don't have any reminders older than one day."),
                ephemeral=True,
            )
            return

        await itx.response.send_message(
            _(itx, "**{count}** reminders have been deleted.").format(count=count),
            ephemeral=True,
        )

        await guild_log.debug(
            itx.user, itx.channel, f"{count} old reminders have been deleted."
        )


class ReminderDummy:
    pass


async def setup(bot) -> None:
    await bot.add_cog(Reminder(bot))

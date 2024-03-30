from datetime import datetime, timedelta
from typing import List, Optional

import dateutil.parser
import discord
from discord.errors import Forbidden, HTTPException
from discord.ext import commands, tasks

from pie import check, i18n, logger, utils
from pie.utils.objects import ConfirmView

from .database import ReminderItem, ReminderStatus

_ = i18n.Translator("modules/reminder").translate
bot_log = logger.Bot.logger()
guild_log = logger.Guild.logger()


class Reminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder.start()

    def cog_unload(self):
        self.reminder.cancel()

    # LOOPS

    @tasks.loop(seconds=30)
    async def reminder(self):
        max_remind_time = datetime.now() + timedelta(seconds=30)

        items = ReminderItem.get_all(
            status=ReminderStatus.WAITING, max_remind_date=max_remind_time
        )

        if items is not None:
            for item in items:
                await self._remind(item)

    @reminder.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

    # HELPER FUNCTIONS

    async def _remind(self, item: ReminderItem):
        reminded_user = await self._get_member(item.recipient_id, item.guild_id)

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

        embed = await self._get_embed(utx, item)

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

    async def _get_embed(self, utx, query):
        reminder_user = await self._get_member(query.author_id, query.guild_id)

        if reminder_user is None:
            reminder_user_name = "_({unknown})_".format(unknown=_(utx, "Unknown user"))
        else:
            reminder_user_name = discord.utils.escape_markdown(
                reminder_user.display_name
            )

        embed = utils.discord.create_embed(
            author=reminder_user,
            title=_(utx, "Reminder"),
        )

        if query.author_id != query.recipient_id:
            embed.add_field(
                name=_(utx, "Reminded by"),
                value=reminder_user_name,
                inline=True,
            )
        if query.message != "":
            embed.add_field(
                name=_(utx, "Message"),
                value=query.message,
                inline=False,
            )
        embed.add_field(name=_(utx, "URL"), value=query.permalink, inline=True)

        return embed

    async def _send_reminder_list(self, ctx, query, *, include_reminded: bool = True):
        reminders = []

        for item in query:
            author = await self._get_member(item.author_id, item.guild_id)
            remind = await self._get_member(item.recipient_id, item.guild_id)

            author_name = (
                author.display_name if author is not None else _(ctx, "(unknown)")
            )
            remind_name = (
                remind.display_name if remind is not None else _(ctx, "(unknown)")
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
            "idx": _(ctx, "ID"),
            "author_name": _(ctx, "Author"),
            "remind_name": _(ctx, "Reminded"),
            "remind_date": _(ctx, "Remind date"),
            "status": _(ctx, "Status"),
            "message": _(ctx, "Message text"),
        }
        if not include_reminded:
            del table_columns["remind_name"]

        table_pages: List[str] = utils.text.create_table(reminders[::-1], table_columns)

        for table_page in table_pages:
            await ctx.send("```" + table_page.replace("`", "'") + "```")

    async def _get_member(self, user_id: int, guild_id: int = 0):
        user = None

        if guild_id > 0:
            guild = self.bot.get_guild(guild_id)
            user = guild.get_member(user_id)

        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except discord.errors.NotFound:
                pass

        return user

    # COMMANDS

    @commands.cooldown(rate=5, per=20.0, type=commands.BucketType.user)
    @check.acl2(check.ACLevel.EVERYONE)
    @commands.command()
    async def remindme(
        self, ctx: commands.Context, datetime_str: str, *, text: Optional[str]
    ):
        """Create reminder for you.

        Args:
            datetime_str: Datetime string (preferably quoted).
            format: DD-MM-YY HH:MM:SS
            text: Optional message to remind.
        """
        text = utils.text.shorten(text, 1024)

        try:
            date = utils.time.parse_datetime(datetime_str)
        except dateutil.parser.ParserError:
            await ctx.reply(
                utils.time.get_datetime_docs(ctx)
                + "\n"
                + _(
                    ctx,
                    "I don't know how to parse `{datetime_str}`, please try again.",
                ).format(datetime_str=datetime_str)
            )
            return

        if date < datetime.now():
            await ctx.reply(
                _(
                    ctx,
                    "Can't use {datetime_str} as time must be in future.",
                ).format(datetime_str=datetime_str)
            )
            return

        item = ReminderItem.add(
            author=ctx.author,
            recipient=ctx.author,
            permalink=ctx.message.jump_url,
            message=text,
            origin_date=ctx.message.created_at,
            remind_date=date,
        )

        await bot_log.debug(
            ctx.author,
            ctx.channel,
            f"Reminder #{item.idx} created for {ctx.author.name} "
            f"to be sent on {item.remind_date}.",
        )

        await ctx.message.add_reaction("✅")
        await ctx.message.author.send(
            _(ctx, "Reminder #{idx} created. It will be sent on **{date}**.").format(
                idx=item.idx, date=utils.time.format_datetime(item.remind_date)
            )
        )

    @commands.guild_only()
    @commands.cooldown(rate=5, per=20.0, type=commands.BucketType.user)
    @check.acl2(check.ACLevel.MEMBER)
    @commands.command()
    async def remind(
        self, ctx, member: discord.Member, datetime_str: str, *, text: Optional[str]
    ):
        """Create reminder for another user.

        Args:
            member: Member to remind.
            datetime_str: Datetime string (preferably quoted).
            text: Optional message to remind.
        """
        text = utils.text.shorten(text, 1024)

        try:
            date = utils.time.parse_datetime(datetime_str)
        except dateutil.parser.ParserError:
            await ctx.reply(
                utils.time.get_datetime_docs(ctx)
                + "\n"
                + _(
                    ctx,
                    "I don't know how to parse `{datetime_str}`, please try again.",
                ).format(datetime_str=datetime_str)
            )
            return

        if date < datetime.now():
            await ctx.reply(
                _(
                    ctx,
                    "Can't use {datetime_str} as time must be in future.",
                ).format(datetime_str=datetime_str)
            )
            return

        item = ReminderItem.add(
            author=ctx.author,
            recipient=member,
            permalink=ctx.message.jump_url,
            message=text,
            origin_date=ctx.message.created_at,
            remind_date=date,
        )

        date = utils.time.format_datetime(date)

        await guild_log.debug(
            ctx.author,
            ctx.channel,
            f"Reminder #{item.idx} created for {member.name} "
            f"to be sent on {item.remind_date}.",
        )

        await ctx.message.add_reaction("✅")
        await ctx.message.author.send(
            _(
                ctx,
                "Reminder #{idx} created for {name}. It will be sent on **{date}**.",
            ).format(
                idx=item.idx,
                name=member.display_name,
                date=utils.time.format_datetime(item.remind_date),
            )
        )

    @check.acl2(check.ACLevel.EVERYONE)
    @commands.group(name="reminder")
    async def reminder_(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder_.command(name="list")
    async def reminder_list(self, ctx, status: str = "WAITING"):
        """List reminders for you.

        Args:
            status: Reminder status (default: WAITING)
        """

        try:
            status = ReminderStatus[status.upper()]
        except KeyError:
            await ctx.send(
                _(ctx, "Invalid status. Allowed: {status}").format(
                    status=ReminderStatus.str_list()
                )
            )
            return

        query = ReminderItem.get_all(recipient=ctx.author, status=status)
        await self._send_reminder_list(ctx, query, include_reminded=False)

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder_.command(name="get")
    async def reminder_get(self, ctx, idx: int):
        """Display reminder details."""
        query = ReminderItem.get_all(guild=ctx.guild, idx=idx)
        if not query:
            await ctx.reply(
                _(ctx, "Reminder with ID {id} does not exist.").format(id=idx)
            )
            return
        item = query[0]
        if ctx.author.id not in (item.author_id, item.recipient_id):
            await ctx.send(
                _(ctx, "You don't have permission to see details of this reminder.")
            )
            return

        created_for: str = _(ctx, "Created {timestamp}").format(
            timestamp=utils.time.format_datetime(item.origin_date)
        )
        if item.author_id != ctx.author.id:
            item_author = ctx.guild.get_member(item.author_id)
            created_for += " " + _(ctx, "by {member}").format(
                member=getattr(item_author, "display_name", str(item.author_id))
            )
        else:
            created_for += " " + _(ctx, "by you")
        scheduled_for: str = _(ctx, "Scheduled for **{timestamp}**").format(
            timestamp=utils.time.format_datetime(item.remind_date)
        )
        if item.recipient_id != ctx.author.id:
            item_recipient = ctx.guild.get_member(item.recipient_id)
            scheduled_for += " " + _(ctx, "for {member}").format(
                member=getattr(item_recipient, "display_name", str(item.recipient_id))
            )
        else:
            scheduled_for += " " + _(ctx, "for you")

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Reminder #{idx}").format(idx=idx),
            description=f"{created_for}\n{scheduled_for}",
        )
        embed.add_field(name=_(ctx, "Content"), value=item.message, inline=False)
        embed.add_field(name=_(ctx, "Status"), value=item.status.value)

        await ctx.reply(embed=embed)

    @commands.guild_only()
    @check.acl2(check.ACLevel.MOD)
    @reminder_.command(name="all")
    async def reminder_all(self, ctx, status: str = "WAITING"):
        """List all guild reminders.

        Args:
            status: Reminder status (default: WAITING)
        """

        try:
            status = ReminderStatus[status.upper()]
        except KeyError:
            await ctx.send(
                _(ctx, "Invalid status. Allowed: {status}").format(
                    status=ReminderStatus.str_list()
                )
            )
            return

        query = ReminderItem.get_all(guild=ctx.guild, status=status)
        await self._send_reminder_list(ctx, query)

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder_.command(name="reschedule", aliases=["postpone", "delay"])
    async def reminder_reschedule(self, ctx, idx: int, datetime_str: str):
        """Reschedule your reminder.

        Args:
            idx: ID of reminder.
            datetime_str: Datetime string (preferably quoted).
        """
        query = ReminderItem.get_all(idx=idx)
        if query is None:
            await ctx.send(
                _(ctx, "Reminder with ID {id} does not exist.").format(id=idx)
            )
            return

        query = query[0]

        if query.recipient_id != ctx.author.id:
            await ctx.send(_(ctx, "Can't reschedule other's reminders."))
            return

        try:
            date = utils.time.parse_datetime(datetime_str)
        except dateutil.parser.ParserError:
            await ctx.reply(
                utils.time.get_datetime_docs(ctx)
                + "\n"
                + _(
                    ctx,
                    "I don't know how to parse `{datetime_str}`, please try again.",
                ).format(datetime_str=datetime_str)
            )
            return

        if date < datetime.now():
            await ctx.send(
                _(ctx, "Can't use {datetime_str} as time must be in future.").format(
                    datetime_str=datetime_str
                )
            )
            return

        print_date = utils.time.format_datetime(date)

        embed = await self._get_embed(ctx, query)
        embed.add_field(
            name=_(ctx, "Original time"),
            value=utils.time.format_datetime(query.remind_date),
            inline=False,
        )
        embed.add_field(
            name=_(ctx, "New time"),
            value=print_date,
            inline=False,
        )
        embed.title = _(ctx, "Do you want to reschedule this reminder?")
        view = ConfirmView(ctx, embed)

        value = await view.send()
        if value is None:
            await ctx.send(_(ctx, "Reschedule timed out."))
        elif value:
            query.remind_date = date
            query.status = ReminderStatus.WAITING
            query.save()
            await ctx.send(_(ctx, "Reminder rescheduled."))
            await guild_log.debug(
                ctx.author,
                ctx.channel,
                f"Reminder #{idx} rescheduled to {datetime_str}.",
            )
        else:
            await ctx.send(_(ctx, "Rescheduling aborted."))

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder_.command(name="delete", aliases=["remove", "cancel"])
    async def reminder_delete(self, ctx, idx: int):
        """Delete reminder

        Args:
            idx: ID of reminder.
        """
        query = ReminderItem.get_all(idx=idx)
        if not query:
            await ctx.send(
                _(ctx, "Reminder with ID {id} does not exist.").format(id=idx)
            )
            return

        query = query[0]

        if query.recipient_id != ctx.author.id:
            await ctx.send(_(ctx, "Can't delete other's reminders."))
            return

        embed = await self._get_embed(ctx, query)
        embed.title = _(ctx, "Do you want to delete this reminder?")
        view = ConfirmView(ctx, embed)

        value = await view.send()
        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            query.delete()
            await ctx.send(_(ctx, "Reminder deleted."))
            await guild_log.debug(
                ctx.author,
                ctx.channel,
                f"Reminder #{idx} cancelled.",
            )
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    @check.acl2(check.ACLevel.EVERYONE)
    @reminder_.command(name="clean")
    async def reminder_clean(self, ctx):
        """Delete all your reminders that finished at least 24 hours ago."""
        before: datetime = datetime.now() - timedelta(hours=24)
        count: int = ReminderItem.batch_delete(ctx.guild, ctx.author, before)

        if not count:
            await ctx.reply(_(ctx, "You don't have any reminders older than one day."))
            return

        await ctx.reply(
            _(ctx, "**{count}** reminders have been deleted.").format(count=count)
        )

        await guild_log.debug(
            ctx.author, ctx.channel, f"{count} old reminders have been deleted."
        )


class ReminderDummy:
    pass


async def setup(bot) -> None:
    await bot.add_cog(Reminder(bot))

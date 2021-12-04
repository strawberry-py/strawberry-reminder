from datetime import datetime, timedelta
from typing import Optional, List

import nextcord
from nextcord.ext import commands, tasks
from nextcord.errors import HTTPException, Forbidden

import dateutil.parser

from pie import check, i18n, logger, utils
from pie.utils.objects import ConfirmView

from .database import ReminderStatus, ReminderItem

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
        print("Reminder loop waiting until ready().")
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

    async def _process_text(self, ctx: commands.Context, text: Optional[str]):
        if text is not None and len(text) > 1024:
            text = text[:1024]
            text = text[:-3] + "```" if text.count("```") % 2 != 0 else text

        return text

    async def _get_embed(self, utx, query):
        reminder_user = await self._get_member(query.recipient_id, query.guild_id)

        if reminder_user is None:
            reminder_user_name = "_({unknown})_".format(unknown=_(utx, "Unknown user"))
        else:
            reminder_user_name = nextcord.utils.escape_markdown(
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

    async def _send_reminder_list(self, ctx, query):
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
            reminder.remind_date = item.remind_date
            reminder.status = item.status.name
            reminder.url = item.permalink.replace("https://discord.com/channels/", "")

            reminders.append(reminder)

        table_pages: List[str] = utils.text.create_table(
            reminders,
            {
                "idx": _(ctx, "Reminder ID"),
                "author_name": _(ctx, "Author"),
                "remind_name": _(ctx, "Reminded"),
                "remind_date": _(ctx, "Remind date"),
                "status": _(ctx, "Status"),
                "url": _(ctx, "URL stub"),
            },
        )

        for table_page in table_pages:
            await ctx.send("```" + table_page + "```")

    async def _get_member(self, user_id: int, guild_id: int = 0):
        user = None

        if guild_id > 0:
            guild = self.bot.get_guild(guild_id)
            user = guild.get_member(user_id)

        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except nextcord.errors.NotFound:
                pass

        return user

    # COMMANDS

    @commands.cooldown(rate=5, per=20.0, type=commands.BucketType.user)
    @commands.command()
    async def remindme(
        self, ctx: commands.Context, datetime_str: str, *, text: Optional[str]
    ):
        """Create reminder for you.
        Args:
            datetime_str: Datetime string (preferably quoted).
            text: Optional message to remind.
        """
        text = await self._process_text(ctx, text)

        try:
            date = utils.time.parse_datetime(datetime_str)
        except dateutil.parser.ParserError:
            await ctx.reply(
                _(
                    ctx,
                    "I don't know how to parse `{datetime_str}`, please try again.",
                ).format(datetime_str=datetime_str)
            )
            return

        ReminderItem.add(
            author=ctx.author,
            recipient=ctx.author,
            permalink=ctx.message.jump_url,
            message=text,
            origin_date=ctx.message.created_at,
            remind_date=date,
        )

        date = utils.time.format_datetime(date)

        await bot_log.debug(
            ctx.author,
            ctx.channel,
            f"Reminder created for {ctx.author.name}",
        )

        await ctx.message.add_reaction("✅")
        await ctx.message.author.send(
            _(ctx, "Reminder for you created. Reminder will be sent: {date}").format(
                date=date
            )
        )

    @commands.guild_only()
    @commands.cooldown(rate=5, per=20.0, type=commands.BucketType.user)
    @commands.check(check.acl)
    @commands.command()
    async def remind(
        self, ctx, member: nextcord.Member, datetime_str: str, *, text: str
    ):
        """Create reminder for another user.
        Args:
            member: Member to remind.
            datetime_str: Datetime string (preferably quoted).
            text: Optional message to remind.
        """
        text = await self._process_text(ctx, text)

        try:
            date = utils.time.parse_datetime(datetime_str)
        except dateutil.parser.ParserError:
            await ctx.reply(
                _(
                    ctx,
                    "I don't know how to parse `{datetime_str}`, please try again.",
                ).format(datetime_str=datetime_str)
            )
            return

        ReminderItem.add(
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
            f"Reminder created for {member.name}",
        )

        await ctx.message.add_reaction("✅")
        await ctx.message.author.send(
            _(ctx, "Reminder for {name} created. Reminder will be sent: {date}").format(
                name=member.display_name, date=date
            )
        )

    @commands.group(name="reminder")
    async def reminder_(self, ctx):
        await utils.discord.send_help(ctx)

    @reminder_.command(name="list")
    async def reminder_list(self, ctx, status: str = "WAITING"):
        """List own reminders.
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
        await self._send_reminder_list(ctx, query)

    @commands.guild_only()
    @commands.check(check.acl)
    @reminder_.command(name="all")
    async def reminder_all(self, ctx, status: str = "WAITING"):
        """List all reminders.
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
                _(ctx, "Reminder with ID {id} does not exists.").format(id=idx)
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
                _(
                    ctx,
                    "I don't know how to parse `{datetime_str}`, please try again.",
                ).format(datetime_str=datetime_str)
            )
            return

        if date < datetime.now():
            await ctx.send(_(ctx, "Reschedule time must be in furuter."))
            return

        print_date = utils.time.format_datetime(date)

        embed = await self._get_embed(ctx, query)
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
            query.delete()
            await ctx.send(_(ctx, "Reminder rescheduled."))
        else:
            await ctx.send(_(ctx, "Rescheduling aborted."))

    @reminder_.command(name="delete", aliases=["remove"])
    async def reminder_delete(self, ctx, idx: int):
        """Delete reminder
        Args:
            idx: ID of reminder.
        """
        query = ReminderItem.get_all(idx=idx)
        if query is None:
            await ctx.send(
                _(ctx, "Reminder with ID {id} does not exists.").format(id=idx)
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
        else:
            await ctx.send(_(ctx, "Deleting aborted."))


class ReminderDummy:
    pass


def setup(bot) -> None:
    bot.add_cog(Reminder(bot))

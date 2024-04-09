from datetime import datetime
from typing import List, Optional

import dateutil.parser
import dateutil.relativedelta
from discord.ext import commands

from pie import check, i18n, logger, utils
from pie.utils import ConfirmView

from .database import CountdownItem

_ = i18n.Translator("modules/reminder").translate
bot_log = logger.Bot.logger()
guild_log = logger.Guild.logger()


class Countdown(commands.Cog):
    """Countdown"""

    def __init__(self, bot):
        self.bot = bot

    async def _process_text(self, ctx: commands.Context, text: Optional[str]):
        """Shortens text to 1024 characters. Places end of the code block at the end if the truncated text contains unclosed block."""
        if text is not None and len(text) > 1024:
            text = text[:1024]
            text = text[:-3] + "```" if text.count("```") % 2 != 0 else text

        return text

    def _get_remaining_time(self, countdown_item: CountdownItem) -> str:
        if countdown_item.countdown_date < datetime.now().astimezone():
            return "Finished"
        else:
            return utils.time.format_seconds(
                (
                    countdown_item.countdown_date - datetime.now().astimezone()
                ).total_seconds()
            )

    async def _get_embed(self, ctx, countdown: CountdownItem):
        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Countdown {name}").format(name=countdown.name),
            description=countdown.message,
        )
        embed.add_field(
            name=_(ctx, "Date"),
            value=utils.time.format_datetime(countdown.countdown_date),
        )
        embed.add_field(
            name=_(ctx, "Remaining time"), value=self._get_remaining_time(countdown)
        )
        embed.add_field(
            name=_(ctx, "Created on"),
            value=utils.time.format_datetime(countdown.origin_date),
            inline=False,
        )
        embed.add_field(name=_(ctx, "URL"), value=countdown.permalink)

        return embed

    async def _send_countdown_list(self, ctx, query):
        countdowns = []

        for item in query:

            countdown = CountdownDummy()
            countdown.idx = item.idx
            countdown.name = item.name
            countdown.countdown_date = item.countdown_date.strftime("%Y-%m-%d %H:%M")
            countdown.remaining_time = self._get_remaining_time(item)
            countdown.message = item.message
            if len(countdown.message) > 30:
                countdown.message = countdown.message[:29] + "\N{HORIZONTAL ELLIPSIS}"

            countdowns.append(countdown)

        table_columns: dict = {
            "idx": _(ctx, "ID"),
            "name": _(ctx, "Name"),
            "countdown_date": _(ctx, "Countdown date"),
            "remaining_time": _(ctx, "Remaining time"),
            "message": _(ctx, "Message"),
        }

        table_pages: List[str] = utils.text.create_table(
            countdowns[::-1], table_columns
        )

        for table_page in table_pages:
            await ctx.send("```" + table_page.replace("`", "'") + "```")

    @check.acl2(check.ACLevel.MEMBER)
    @commands.group(name="countdown")
    async def countdown_(self, ctx: commands.Context):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MEMBER)
    @countdown_.command(name="set")
    async def countdown_set(
        self,
        ctx: commands.Context,
        name: str,
        datetime_str: str,
        *,
        text: Optional[str],
    ):
        """Set new countdown.

        Args:
            name: Countdown name
            datetime_str: Datetime string (preferably quoted)
            text: Optional message
        """

        if CountdownItem.get(ctx.author.id, name):
            await ctx.reply(
                _(ctx, "Countdown '{name}' already exists.").format(name=name)
            )
            return

        text = await self._process_text(ctx, text)

        try:
            date = utils.time.parse_datetime(datetime_str)
        except dateutil.parser.ParserError:
            await ctx.reply(
                _(
                    ctx,
                    "I don't know how to parse `{datetime_str}`, pleasy try again.",
                ).format(datetime_str=datetime_str)
            )
            return

        if date < datetime.now():
            await ctx.reply(_(ctx, "Time must be in future."))
            return

        item = CountdownItem.add(
            guild_id=ctx.author.guild.id if hasattr(ctx.author, "guild") else 0,
            author_id=ctx.author.id,
            name=name,
            permalink=ctx.message.jump_url,
            message=text,
            origin_date=ctx.message.created_at,
            countdown_date=date,
        )

        await bot_log.debug(
            ctx.author,
            ctx.channel,
            f"Countdown #{item.idx} ({item.countdown_date}) "
            f"created for {ctx.author.name}.",
        )
        await ctx.message.add_reaction("✅")

        await ctx.reply(
            _(
                ctx,
                "Countdown '{name}' to **{date}** created. Remaining time is {time}.",
            ).format(
                name=name,
                date=utils.time.format_datetime(item.countdown_date),
                time=self._get_remaining_time(item),
            )
        )

    @check.acl2(check.ACLevel.MEMBER)
    @countdown_.command(name="get")
    async def countdown_get(self, ctx: commands.Context, name: str):
        """Get countdown details.

        Args:
            name: Countdown name
        """
        countdown = CountdownItem.get(author_id=ctx.author.id, name=name)

        if not countdown:
            await ctx.reply(
                _(ctx, "Countdown '{name}' does not exist.").format(name=name)
            )
            return

        if ctx.author.id != countdown.author_id:
            await ctx.send(_(ctx, "You don't have permission to see this countdown."))
            return

        embed = await self._get_embed(ctx, countdown=countdown)

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @countdown_.command(name="delete")
    async def countdown_delete(self, ctx: commands.Context, name: str):
        """Delete countdown

        Args:
            name: Countdown name
        """
        countdown = CountdownItem.get(author_id=ctx.author.id, name=name)
        if not countdown:
            await ctx.reply(
                _(ctx, "Countdown '{name}' does not exist.").format(name=name)
            )
            return

        embed = await self._get_embed(ctx, countdown=countdown)
        embed.title = _(ctx, "Do you want to delete this countdown?")
        view = ConfirmView(ctx, embed)

        value = await view.send()
        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            countdown.delete()
            await ctx.send(_(ctx, "Countdown deleted."))
            await bot_log.debug(
                ctx.author,
                ctx.channel,
                f"Countdown #{countdown.idx} ({countdown.countdown_date}) deleted.",
            )
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    @check.acl2(check.ACLevel.MEMBER)
    @countdown_.command(name="list")
    async def countdown_list(self, ctx: commands.Context, show_finished: bool = False):
        """List your countdowns

        Args:
            show_finished: True/False whether to show finished countdowns
        """
        if show_finished:
            query = CountdownItem.get_all(author_id=ctx.author.id)
        else:
            query = CountdownItem.get_all(
                author_id=ctx.author.id, min_countdown_date=datetime.now()
            )

        await self._send_countdown_list(ctx, query)


class CountdownDummy:
    pass


async def setup(bot) -> None:
    await bot.add_cog(Countdown(bot))

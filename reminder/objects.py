from datetime import datetime

import dateutil
import discord

from pie import i18n, logger, utils
from pie.utils.objects import ConfirmView

from .database import ReminderItem, ReminderStatus
from .utils import get_reminder_embed

_ = i18n.Translator("modules/reminder").translate

bot_log = logger.Bot.logger()


class RemindModal(discord.ui.Modal):
    def __init__(
        self,
        bot,
        itx: discord.Interaction,
        title: str,
        recipient: discord.Member,
        message: discord.Message = None,
        reminder: ReminderItem = None,
    ) -> None:
        super().__init__(title=title, custom_id="remindme_modal", timeout=900)

        self.bot = bot
        self.title = title
        self.message = message
        self.recipient = recipient
        self.reminder = reminder
        self.datetime_input = discord.ui.TextInput(
            label=_(itx, "Date / time:"),
            custom_id=self.custom_id + "_datetime",
            style=discord.TextStyle.short,
            required=True,
            default=(
                utils.time.format_datetime(reminder.remind_date) if reminder else None
            ),
            placeholder="24-12-2024 12:24:36 / 1w5d13h36m",
            max_length=19,
            min_length=2,
        )

        self.message_input = discord.ui.TextInput(
            label=_(itx, "Message:"),
            custom_id=self.custom_id + "_message",
            style=discord.TextStyle.long,
            required=False,
            default=reminder.message if reminder else None,
            placeholder="(Optional) Reminder message",
            max_length=1024,
        )
        self.add_item(self.datetime_input)
        self.add_item(self.message_input)

    async def on_submit(self, itx: discord.Interaction) -> None:
        try:
            date = utils.time.parse_datetime(self.datetime_input.value)
        except dateutil.parser.ParserError:
            await itx.response.send_message(
                utils.time.get_datetime_docs(itx)
                + "\n"
                + _(
                    itx,
                    "I don't know how to parse `{datetime_str}`, please try again.",
                ).format(datetime_str=self.datetime_input.value),
                ephemeral=True,
            )
            self.stop()
            return

        if date < datetime.now():
            await itx.response.send_message(
                _(
                    itx,
                    "Can't use {datetime_str} as time must be in future.",
                ).format(datetime_str=self.datetime_input.value),
                ephemeral=True,
            )
            self.stop()
            return

        message = utils.text.shorten(self.message_input.value, 1024)

        if self.reminder:
            await self._edit_reminder(itx, message, date)
        else:
            await self._add_reminder(itx, message, date)

        self.stop()

    async def _add_reminder(
        self, itx: discord.Interaction, message: str, date: datetime
    ) -> None:
        item = ReminderItem.add(
            author=itx.user,
            recipient=self.recipient,
            permalink=self.message.jump_url if self.message else "",
            message=message,
            origin_date=datetime.now(),
            remind_date=date,
        )

        await bot_log.debug(
            itx.user,
            itx.channel,
            f"Reminder #{item.idx} created for {itx.user.name} "
            f"to be sent on {item.remind_date}.",
        )

        response: str = _(
            itx, "Reminder #{idx} created. It will be sent on **{date}**."
        ).format(idx=item.idx, date=utils.time.format_datetime(item.remind_date))

        await itx.user.send(response)

        await itx.response.send_message(response, ephemeral=True)

    async def _edit_reminder(
        self, itx: discord.Interaction, message: str, date: datetime
    ) -> None:
        print_date = utils.time.format_datetime(date)

        embed = await get_reminder_embed(self.bot, itx, self.reminder)
        embed.add_field(
            name=_(itx, "New time"),
            value=print_date,
            inline=False,
        )

        message = utils.text.shorten(self.message_input.value, 1024)

        embed.add_field(
            name=_(itx, "New message"),
            value=message,
            inline=False,
        )
        embed.title = _(itx, "Do you want to edit this reminder?")
        view = ConfirmView(itx, embed)

        value = await view.send()
        if value is None:
            await view.itx.response.send_message(_(itx, "Reminder edit timed out."))
        elif value:
            self.reminder.remind_date = date
            self.reminder.status = ReminderStatus.WAITING
            self.reminder.message = message
            self.reminder.save()
            await view.itx.response.send_message(
                _(itx, "Reminder edited."), ephemeral=True
            )
            await bot_log.debug(
                itx.user,
                itx.channel,
                f"Reminder #{self.reminder.idx} edited and scheduled to {print_date}.",
            )
        else:
            await view.itx.response.send_message(
                _(itx, "Reminder edit aborted."), ephemeral=True
            )

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        raise error

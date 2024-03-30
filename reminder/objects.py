from datetime import datetime

import dateutil
import discord

from pie import i18n, logger, utils

from .database import ReminderItem

_ = i18n.Translator("modules/reminder").translate

bot_log = logger.Bot.logger()


class RemindModal(discord.ui.Modal):
    def __init__(
        self,
        bot,
        title: str,
        label: str,
        recipient: discord.Member,
        message: discord.Message = None,
    ) -> None:
        super().__init__(title=title, custom_id="remindme_modal", timeout=900)

        self.bot = bot
        self.title = title
        self.message = message
        self.recipient = recipient
        self.datetime_input = discord.ui.TextInput(
            label=label,
            custom_id=self.custom_id + "_datetime",
            style=discord.TextStyle.short,
            required=True,
            placeholder="24-12-2024 12:24:36 / 1w5d13h36m",
            max_length=19,
            min_length=2,
        )

        self.message_input = discord.ui.TextInput(
            label=label,
            custom_id=self.custom_id + "_message",
            style=discord.TextStyle.long,
            required=False,
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

        item = ReminderItem.add(
            author=itx.user,
            recipient=self.recipient,
            permalink=self.message.jump_url if message else "",
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

        await itx.user.send(
            _(itx, "Reminder #{idx} created. It will be sent on **{date}**.").format(
                idx=item.idx, date=utils.time.format_datetime(item.remind_date)
            )
        )

        await itx.response.send_message(
            _(itx, "Reminder #{idx} created. It will be sent on **{date}**.").format(
                idx=item.idx, date=utils.time.format_datetime(item.remind_date)
            ),
            ephemeral=True,
        )

        self.stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        raise error

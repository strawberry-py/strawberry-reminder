from __future__ import annotations

from datetime import datetime

import enum
import nextcord
from sqlalchemy import BigInteger, Column, Integer, String, DateTime, Enum
from typing import List, Dict

from pie.database import database, session


class ReminderStatus(enum.Enum):
    WAITING: str = "WAITING"
    REMINDED: str = "REMINDED"
    FAILED: str = "FAILED"

    def str_list() -> str:
        return ", ".join([e.name for e in ReminderStatus])


class ReminderItem(database.base):
    """Represents a database Reminder item for :class:`Reminder` module.

    Attributes:
        idx: The database ID.
        guild_id: ID of the guild.
        author_id: User ID of reminder author.
        recipient_id: User ID of reminded user.
        permalink: Message URL.
        message: Reminder text (None if empty).
        origin_date: Date of creation.
        remind_date: Date for reminding
        status: Status of reminder
    """

    __tablename__ = "reminder_reminder_reminderitem"

    idx = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, default=None)
    author_id = Column(BigInteger, default=None)
    recipient_id = Column(BigInteger, default=None)
    permalink = Column(String, default=None)
    message = Column(String, default=None)
    origin_date = Column(DateTime(timezone=True), default=None)
    remind_date = Column(DateTime(timezone=True), default=None)
    status = Column(Enum(ReminderStatus), default=ReminderStatus.WAITING)

    @staticmethod
    def add(
        author: nextcord.Member,
        recipient: nextcord.Member,
        permalink: str,
        message: str,
        origin_date: datetime,
        remind_date: datetime,
    ) -> ReminderItem:
        """Creates a new ReminderItem in the database.

        Args:
            author: Reminder author.
            recipient: Reminder recipient.
            permalink: URL of reminder message.
            message: Reminder text (None if empty).
            origin_date: Date of creation.
            remind_date: Date for reminding

        Raises:
            ValueError: End time already passed.

        Returns:
            The created database item.
        """
        origin_date = datetime.now()
        if remind_date < origin_date:
            raise ValueError

        item = ReminderItem(
            guild_id=author.guild.id if hasattr(author, "guild") else 0,
            author_id=author.id,
            recipient_id=recipient.id,
            permalink=permalink,
            message=message,
            origin_date=origin_date,
            remind_date=remind_date,
            status=ReminderStatus.WAITING,
        )

        session.add(item)
        session.commit()
        return item

    @staticmethod
    def get_all(
        guild: nextcord.Guild = None,
        idx: int = None,
        recipient: nextcord.Member = None,
        status: ReminderStatus = None,
        min_origin_date: datetime = None,
        max_origin_date: datetime = None,
        min_remind_date: datetime = None,
        max_remind_date: datetime = None,
    ) -> List[ReminderItem]:
        """Retreives List of ReminderItem filtered by Guild ID.

        Args:
            guild: Guild whose items are to be returned.
            idx: ID of reminder item
            recipient: nextcord.Member object user whose items are to be returned.
            status: Status of items to be returned
            min_origin_date: Filter items created after this date.
            max_origin_date: Filter items created before this date.
            min_remind_date: Filter items being reminded after this date.
            max_remind_date: Filter items being reminded before this date.

        Returns:
            :class:`List[ReminderItem]`: The retrieved reminder items ordered by remind_date descending.
        """
        query = session.query(ReminderItem)

        if guild is not None:
            query = query.filter_by(guild_id=guild.id)

        if idx is not None:
            query = query.filter_by(idx=idx)

        if recipient is not None:
            query = query.filter_by(recipient_id=recipient.id)

        if status is not None:
            query = query.filter_by(status=status)

        if min_origin_date is not None:
            query = query.filter(ReminderItem.origin_date > min_origin_date)

        if max_origin_date is not None:
            query = query.filter(ReminderItem.origin_date < max_origin_date)

        if min_remind_date is not None:
            query = query.filter(ReminderItem.remind_date > min_remind_date)

        if max_remind_date is not None:
            query = query.filter(ReminderItem.remind_date < max_remind_date)

        query = query.order_by(ReminderItem.remind_date.desc())

        return query.all()

    def delete(self):
        """
        Deletes the item from the database.
        """
        session.delete(self)
        session.commit()

    def __repr__(self) -> str:
        return (
            f'<ReminderItem idx="{self.idx}" guild_id="{self.guild_id}" '
            f'author_id="{self.author_id}" recipient_id="{self.recipient_id}" '
            f'permalink="{self.permalink}" message="{self.message}" '
            f'origin_date="{self.origin_date}" remind_date="{self.remind_date}" '
            f'status="{self.status}">'
        )

    def dump(self) -> Dict:
        """Dumps ReminderItem into a dictionary.

        Returns:
            :class:`Dict`: The ReminderItem as a dictionary.
        """
        return {
            "idx": self.idx,
            "guild_id": self.guild_id,
            "author_id": self.author_id,
            "recipient_id": self.recipient_id,
            "permalink": self.permalink,
            "message": self.message,
            "origin_date": self.origin_date,
            "remind_date": self.remind_date,
            "status": self.status,
        }

    def save(self):
        """Commits the ReminderItem to the database."""
        session.commit()

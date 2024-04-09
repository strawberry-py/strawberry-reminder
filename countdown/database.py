from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from pie.database import database, session


class CountdownItem(database.base):
    """Represents a database Countdown item for :class:`Reminder` module.

    Attributes:
        idx: The database ID.
        guild_id: ID of the guild.
        author_id: User ID of reminder author.
        permalink: Message URL.
        message: Reminder text (None if empty).
        origin_date: Date of creation.
        countdown_date: Date for reminding
        status: Status of reminder
    """

    __tablename__ = "fun_countdown_item"

    idx = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, default=None)
    author_id = Column(BigInteger, default=None)
    name = Column(String, default=None)
    permalink = Column(String, default=None)
    message = Column(String, default=None)
    origin_date = Column(DateTime(timezone=True), default=None)
    countdown_date = Column(DateTime(timezone=True), default=None)

    @staticmethod
    def add(
        guild_id: int,
        author_id: int,
        name: str,
        permalink: str,
        message: str,
        origin_date: datetime,
        countdown_date: datetime,
    ) -> CountdownItem:
        """Creates a new CountdownItem in the database.

        Args:
            author_id: Countdown author.
            name: Event name
            permalink: URL of countdown message.
            message: Countdown text (None if empty).
            origin_date: Date of creation.
            countdown_date: Date for reminding

        Raises:
            ValueError: End time already passed.

        Returns:
            The created database item.
        """

        origin_date = datetime.now()
        if countdown_date < origin_date:
            raise ValueError

        item = CountdownItem(
            guild_id=guild_id,
            author_id=author_id,
            name=name,
            permalink=permalink,
            message=message,
            origin_date=origin_date,
            countdown_date=countdown_date,
        )

        session.add(item)
        session.commit()
        return item

    @staticmethod
    def get(author_id: int, name: str) -> Optional[CountdownItem]:
        query = (
            session.query(CountdownItem)
            .filter_by(author_id=author_id, name=name)
            .one_or_none()
        )
        return query

    @staticmethod
    def get_all(
        guild_id: int = None,
        author_id: int = None,
        min_origin_date: datetime = None,
        max_origin_date: datetime = None,
        min_countdown_date: datetime = None,
        max_countdown_date: datetime = None,
    ) -> List[CountdownItem]:
        """Retreives List of CountdownItem filtered by Guild ID.

        Args:
            guild_id: Guild whose items are to be returned.
            author_id: User whose items are to be returned.
            min_origin_date: Filter items created after this date.
            max_origin_date: Filter items created before this date.
            min_countdown_date: Filter items being reminded after this date.
            max_countdown_date: Filter items being reminded before this date.

        Returns:
            :class:`List[CountdownItem]`: The retrieved countdown items ordered by countdown_date descending.
        """
        query = session.query(CountdownItem)

        if guild_id is not None:
            query = query.filter_by(guild_id=guild_id)

        if author_id is not None:
            query = query.filter_by(author_id=author_id)

        if min_origin_date is not None:
            query = query.filter(CountdownItem.origin_date > min_origin_date)

        if max_origin_date is not None:
            query = query.filter(CountdownItem.origin_date < max_origin_date)

        if min_countdown_date is not None:
            query = query.filter(CountdownItem.countdown_date > min_countdown_date)

        if max_countdown_date is not None:
            query = query.filter(CountdownItem.countdown_date < max_countdown_date)

        query = query.order_by(CountdownItem.countdown_date.desc())

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
            f'author_id="{self.author_id}" name="{self.name}">'
            f'permalink="{self.permalink}" message="{self.message}" '
            f'origin_date="{self.origin_date}" remind_date="{self.countdown_date}">'
        )

    def dump(self) -> Dict:
        """Dumps CountdownItem into a dictionary.

        Returns:
            :class:`Dict`: The CountdownItem as a dictionary.
        """
        return {
            "idx": self.idx,
            "guild_id": self.guild_id,
            "author_id": self.author_id,
            "name": self.name,
            "permalink": self.permalink,
            "message": self.message,
            "origin_date": self.origin_date,
            "countdown_date": self.countdown_date,
        }

    def save(self):
        """Commits the CountdownItem to the database."""
        session.commit()

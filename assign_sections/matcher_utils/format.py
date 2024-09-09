import datetime

from .matcher import Slot


def format_time(time: datetime.time) -> str:
    """
    Format a `datetime.time` object into a time string.
    """
    if time.minute == 0:
        return time.strftime("%I%p")
    return time.strftime("%I:%M%p")


def format_days(day_list: list[int]) -> str:
    """
    Formats a list of day integers (where Monday = 0, Sunday = 6) into a string.
    """
    days = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]
    return "".join(days[day] for day in day_list)


def format_slot(slot: Slot) -> str:
    """
    Convert a discussion info dict into a human-readable string.
    """
    start_str = format_time(slot.start_time)
    end_str = format_time(slot.end_time)
    return f"{format_days(slot.days)} {start_str}-{end_str} @ {slot.location}"

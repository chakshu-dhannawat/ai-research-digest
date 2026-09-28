from datetime import datetime, timedelta, timezone

# Japan Standard Time. Japan observes no daylight saving, so a fixed +09:00
# offset is always correct and avoids a system tzdata dependency on slim images.
JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    """Current time as a timezone-aware datetime in JST.

    Use this for all wall-clock 'now' that drives date labels, day-windows, and
    recency cutoffs so the system's notion of 'today' matches the JST calendar
    day the newsletter is sent on (the cron also fires in Asia/Tokyo)."""
    return datetime.now(JST)


def format_digest_date(dt=None, fmt="%Y-%m-%d") -> str:
    """Format a JST datetime for display. Defaults to today."""
    return (dt or now_jst()).strftime(fmt)

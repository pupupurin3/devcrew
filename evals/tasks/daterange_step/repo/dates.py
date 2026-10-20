from datetime import date, timedelta


def daterange(start: date, end: date):
    """Yield each date from start up to, but not including, end."""
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)

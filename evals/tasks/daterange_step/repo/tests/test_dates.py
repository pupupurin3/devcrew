from datetime import date
from dates import daterange


def test_daily():
    days = list(daterange(date(2024, 1, 1), date(2024, 1, 4)))
    assert days == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]

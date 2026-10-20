from datetime import date
import pytest
from dates import daterange


def test_weekly():
    got = list(daterange(date(2024, 1, 1), date(2024, 1, 22), step=7))
    assert got == [date(2024, 1, 1), date(2024, 1, 8), date(2024, 1, 15)]


def test_default_still_daily():
    assert len(list(daterange(date(2024, 2, 27), date(2024, 3, 2)))) == 4


def test_end_exclusive_with_step():
    got = list(daterange(date(2024, 1, 1), date(2024, 1, 15), step=7))
    assert got == [date(2024, 1, 1), date(2024, 1, 8)]


@pytest.mark.parametrize("step", [0, -1])
def test_bad_step(step):
    with pytest.raises(ValueError):
        list(daterange(date(2024, 1, 1), date(2024, 1, 2), step=step))

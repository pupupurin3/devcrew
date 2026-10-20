import pytest
from roman import from_roman, to_roman


def test_examples():
    assert from_roman("MCMXCIV") == 1994
    assert from_roman("XLII") == 42


def test_round_trip():
    for n in range(1, 4000):
        assert from_roman(to_roman(n)) == n


@pytest.mark.parametrize("bad", ["", "IIII", "VX", "IC", "xii", "MMMM", "VV", "IIV", "ABC"])
def test_invalid(bad):
    with pytest.raises(ValueError):
        from_roman(bad)

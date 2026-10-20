import pytest
from pager import paginate, page_count


def test_second_page_no_overlap():
    assert paginate(list(range(10)), 2, 3) == [3, 4, 5]


def test_last_partial_page():
    assert paginate(list(range(10)), 4, 3) == [9]


def test_past_end_empty():
    assert paginate(list(range(10)), 5, 3) == []


def test_page_count_rounds_up():
    assert page_count(list(range(10)), 3) == 4
    assert page_count(list(range(9)), 3) == 3
    assert page_count([], 3) == 0


@pytest.mark.parametrize("page,per", [(0, 3), (-1, 3), (1, 0)])
def test_invalid_args(page, per):
    with pytest.raises(ValueError):
        paginate([1, 2, 3], page, per)

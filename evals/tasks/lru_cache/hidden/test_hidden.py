import pytest
from lru import LRUCache


def test_evicts_least_recent():
    c = LRUCache(2)
    c.put("a", 1); c.put("b", 2)
    c.get("a")
    c.put("c", 3)
    assert c.get("b") is None
    assert c.get("a") == 1 and c.get("c") == 3


def test_update_refreshes_recency():
    c = LRUCache(2)
    c.put("a", 1); c.put("b", 2)
    c.put("a", 10)
    c.put("c", 3)
    assert c.get("a") == 10
    assert c.get("b") is None


def test_len():
    c = LRUCache(3)
    for i in range(5):
        c.put(i, i)
    assert len(c) == 3


def test_falsy_values():
    c = LRUCache(1)
    c.put("z", 0)
    assert c.get("z") == 0


def test_bad_capacity():
    with pytest.raises(ValueError):
        LRUCache(0)

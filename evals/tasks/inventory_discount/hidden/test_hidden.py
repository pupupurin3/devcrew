import pytest
import pricing
from inventory import Inventory


def test_discounts_applied():
    inv = Inventory()
    inv.add("a", 10.0, 2)
    inv.add("b", 10.0, 2, "clearance")
    inv.add("c", 10.0, 1, "seasonal")
    assert inv.total_value() == pytest.approx(20 + 10 + 8)


def test_uses_pricing_module(monkeypatch):
    monkeypatch.setitem(pricing.DISCOUNTS, "standard", 0.1)
    inv = Inventory()
    inv.add("a", 10.0, 1)
    assert inv.total_value() == pytest.approx(9.0)


def test_negative_quantity():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.add("a", 1.0, -1)


def test_restock_existing():
    inv = Inventory()
    inv.add("a", 2.0, 1, "clearance")
    inv.add("a", 2.0, 3, "clearance")
    assert inv.total_value() == pytest.approx(4.0)

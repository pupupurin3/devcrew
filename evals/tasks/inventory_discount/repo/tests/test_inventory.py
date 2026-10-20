from inventory import Inventory


def test_standard_value():
    inv = Inventory()
    inv.add("a", 10.0, 3)
    assert inv.total_value() == 30.0

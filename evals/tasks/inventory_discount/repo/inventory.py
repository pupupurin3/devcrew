from dataclasses import dataclass


@dataclass
class Item:
    sku: str
    unit_price: float
    quantity: int
    category: str = "standard"


class Inventory:
    def __init__(self):
        self.items: dict[str, Item] = {}

    def add(self, sku, unit_price, quantity, category="standard"):
        if sku in self.items:
            self.items[sku].quantity += quantity
        else:
            self.items[sku] = Item(sku, unit_price, quantity, category)

    def total_value(self) -> float:
        return sum(i.unit_price * i.quantity for i in self.items.values())

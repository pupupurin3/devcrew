# Fraction taken off the unit price, by category.
DISCOUNTS = {
    "clearance": 0.5,
    "seasonal": 0.2,
}


def discounted_price(unit_price: float, category: str) -> float:
    return unit_price * (1 - DISCOUNTS.get(category, 0.0))

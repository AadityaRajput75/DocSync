def in_stock(quantity: int, available: int):
    """Check whether enough units are available."""
    return quantity <= available


def reserve(quantity: int, available: int):
    """Return inventory remaining after reservation."""
    if quantity > available:
        raise ValueError("Insufficient stock")
    return available - quantity

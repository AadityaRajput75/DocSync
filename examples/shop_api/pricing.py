def calculate_total(price: float, quantity: int, discount: float = 0):
    """Calculate total after a fractional discount."""
    return round(price * quantity * (1 - discount), 2)


def validate_discount(code: str):
    """Look up a discount fraction, returning zero for unknown codes."""
    return {"WELCOME": 0.1}.get(code, 0)

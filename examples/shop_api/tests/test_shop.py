from pricing import calculate_total, validate_discount


def test_discount():
    assert calculate_total(10, 2, validate_discount("WELCOME")) == 18


def test_unknown_discount():
    assert validate_discount("UNKNOWN") == 0

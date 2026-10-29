from validation import valid_priority, valid_title


def test_title():
    assert valid_title(" Write docs ")
    assert not valid_title("")


def test_priority():
    assert valid_priority(1)
    assert not valid_priority(6)

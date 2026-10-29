def valid_title(title: str):
    """Titles must contain between one and eighty non-edge-whitespace characters."""
    return 1 <= len(title.strip()) <= 80


def valid_priority(priority: int):
    """Priorities are integers from one through five."""
    return 1 <= priority <= 5

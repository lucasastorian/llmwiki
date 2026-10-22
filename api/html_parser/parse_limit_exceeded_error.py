class ParseLimitExceededError(Exception):
    """The document would render past the parser's output budget."""

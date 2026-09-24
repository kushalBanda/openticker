"""Errors more than one use case raises."""


class UnknownOrderError(Exception):
    pass


class BatchTooLargeError(ValueError):
    """More items in one call than MAX_BATCH."""

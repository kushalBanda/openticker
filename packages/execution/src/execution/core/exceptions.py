class ExecutionError(Exception):
    """Base exception for the execution package."""


class UnknownRiskCheckError(ExecutionError):
    """Raised when config names a risk check that was never registered."""


class InvalidTransitionError(ExecutionError):
    """Raised when an order lifecycle transition is not allowed from the current state."""

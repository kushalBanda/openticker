"""Errors raised by plugin/lib/math functions when input data is unusable.

Ported from quant.core.exceptions, trimmed to the one exception every
math module actually raises. UnknownSignalError/UnknownSetupError are
dropped, dispatch-by-name in a skill script raises a plain ValueError
instead of a dedicated exception type.
"""


class InsufficientDataError(Exception):
    """Not enough valid observations to compute a result."""

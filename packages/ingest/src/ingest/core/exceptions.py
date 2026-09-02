class AdapterError(Exception):
    pass


class AuthExpiredError(AdapterError):
    pass


class RateLimitError(AdapterError):
    pass


class DataUnavailableError(AdapterError):
    pass

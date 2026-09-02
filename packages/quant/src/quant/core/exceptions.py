class ResearchError(Exception):
    pass


class UnknownSignalError(ResearchError):
    pass


class InsufficientDataError(ResearchError):
    pass

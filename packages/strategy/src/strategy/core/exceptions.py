class StrategyEngineError(Exception):
    pass


class UnknownStrategyError(StrategyEngineError):
    pass


class UnknownOrderError(StrategyEngineError):
    pass


class OrderNotCancellableError(StrategyEngineError):
    pass

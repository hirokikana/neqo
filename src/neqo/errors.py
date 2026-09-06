class NeqoError(Exception):
    """Base error for errors reported by NEQO."""


class ConfigError(NeqoError, ValueError):
    pass


class MacroError(NeqoError, ValueError):
    pass


class QueryError(NeqoError):
    def __init__(self, message: str, query_id: str | None = None):
        super().__init__(message)
        self.query_id = query_id

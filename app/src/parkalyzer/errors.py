class ParkalyzerError(Exception):
    """Base exception for all parkalyzer errors."""


class ConfigurationError(ParkalyzerError):
    """Raised when a required configuration value is missing or invalid."""


class DatabaseError(ParkalyzerError):
    """Raised when a database operation fails unexpectedly."""


class ORSError(ParkalyzerError):
    """Raised when the ORS API returns an error or is unreachable."""


class ORSTimeoutError(ORSError):
    """Raised when an ORS request times out."""


class ORSResponseError(ORSError):
    """Raised when ORS returns a non-2xx response."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"ORS returned HTTP {status_code}: {body[:200]}")


class OSMDataError(ParkalyzerError):
    """Raised when OSM source data is missing or has an unexpected structure."""

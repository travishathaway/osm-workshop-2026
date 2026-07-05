from parkalyzer.errors import (
    ConfigurationError,
    DatabaseError,
    OSMDataError,
    ORSError,
    ORSResponseError,
    ORSTimeoutError,
    ParkalyzerError,
)


def test_all_errors_inherit_from_parkalyzer_error():
    for exc_class in [
        ConfigurationError,
        DatabaseError,
        OSMDataError,
        ORSError,
        ORSResponseError,
        ORSTimeoutError,
    ]:
        assert issubclass(exc_class, ParkalyzerError), f"{exc_class.__name__} must inherit ParkalyzerError"


def test_ors_timeout_error_is_ors_error():
    assert issubclass(ORSTimeoutError, ORSError)


def test_ors_response_error_is_ors_error():
    assert issubclass(ORSResponseError, ORSError)


def test_ors_response_error_stores_status_code():
    exc = ORSResponseError(status_code=429, body="rate limited")
    assert exc.status_code == 429


def test_ors_response_error_stores_body():
    exc = ORSResponseError(status_code=500, body="internal error")
    assert exc.body == "internal error"


def test_ors_response_error_message_includes_status():
    exc = ORSResponseError(status_code=404, body="not found")
    assert "404" in str(exc)


def test_ors_response_error_truncates_long_body():
    long_body = "x" * 500
    exc = ORSResponseError(status_code=500, body=long_body)
    assert len(exc.body) == 500  # body stored in full
    assert len(str(exc)) < len(long_body) + 50  # message is truncated

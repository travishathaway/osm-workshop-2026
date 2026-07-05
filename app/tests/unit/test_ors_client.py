from unittest.mock import MagicMock, patch

import httpx
import pytest

from parkalyzer.errors import ORSResponseError, ORSTimeoutError
from parkalyzer.ors import MatrixResult, ORSClient

BASE_URL = "http://localhost:8080"

SAMPLE_MATRIX_RESPONSE = {
    "durations": [[0.0, 120.5], [130.2, 0.0]],
    "distances": [[0.0, 850.3], [860.1, 0.0]],
    "sources": [{"location": [8.8, 53.1]}],
    "destinations": [{"location": [8.9, 53.2]}],
}


@patch("parkalyzer.ors.httpx.Client")
def test_health_check_returns_true_on_200(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client_cls.return_value.get.return_value = mock_response

    client = ORSClient(BASE_URL)
    assert client.health_check() is True


@patch("parkalyzer.ors.httpx.Client")
def test_health_check_returns_false_on_503(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_client_cls.return_value.get.return_value = mock_response

    client = ORSClient(BASE_URL)
    assert client.health_check() is False


@patch("parkalyzer.ors.httpx.Client")
def test_health_check_returns_false_on_connection_error(mock_client_cls):
    mock_client_cls.return_value.get.side_effect = httpx.ConnectError("refused")

    client = ORSClient(BASE_URL)
    assert client.health_check() is False


@patch("parkalyzer.ors.httpx.Client")
def test_matrix_raises_ors_timeout_error(mock_client_cls):
    mock_client_cls.return_value.post.side_effect = httpx.TimeoutException("timed out")

    client = ORSClient(BASE_URL)
    with pytest.raises(ORSTimeoutError):
        client.matrix(locations=[(8.8, 53.1), (8.9, 53.2)])


@patch("parkalyzer.ors.httpx.Client")
def test_matrix_raises_ors_response_error_on_400(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad request"
    mock_client_cls.return_value.post.return_value = mock_response

    client = ORSClient(BASE_URL)
    with pytest.raises(ORSResponseError) as exc_info:
        client.matrix(locations=[(8.8, 53.1), (8.9, 53.2)])
    assert exc_info.value.status_code == 400


@patch("parkalyzer.ors.httpx.Client")
def test_matrix_parses_result_correctly(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = SAMPLE_MATRIX_RESPONSE
    mock_client_cls.return_value.post.return_value = mock_response

    client = ORSClient(BASE_URL)
    result = client.matrix(locations=[(8.8, 53.1), (8.9, 53.2)])

    assert isinstance(result, MatrixResult)
    assert result.durations == [[0.0, 120.5], [130.2, 0.0]]
    assert result.distances == [[0.0, 850.3], [860.1, 0.0]]
    assert len(result.sources) == 1
    assert len(result.destinations) == 1


@patch("parkalyzer.ors.httpx.Client")
def test_matrix_sends_sources_and_destinations(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"durations": [[10.0]], "distances": [[100.0]]}
    mock_client = mock_client_cls.return_value
    mock_client.post.return_value = mock_response

    client = ORSClient(BASE_URL)
    client.matrix(
        locations=[(8.8, 53.1), (8.9, 53.2), (9.0, 53.3)],
        sources=[0],
        destinations=[1, 2],
    )

    call_kwargs = mock_client.post.call_args
    payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
    assert payload["sources"] == [0]
    assert payload["destinations"] == [1, 2]


def test_client_is_context_manager():
    with patch("parkalyzer.ors.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        with ORSClient(BASE_URL) as client:
            assert isinstance(client, ORSClient)
        mock_client.close.assert_called_once()


@patch("parkalyzer.ors.httpx.Client")
def test_matrix_default_metrics_include_duration_and_distance(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"durations": [], "distances": []}
    mock_client = mock_client_cls.return_value
    mock_client.post.return_value = mock_response

    client = ORSClient(BASE_URL)
    client.matrix(locations=[(8.8, 53.1)])

    payload = mock_client.post.call_args[1]["json"]
    assert "duration" in payload["metrics"]
    assert "distance" in payload["metrics"]

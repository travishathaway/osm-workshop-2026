"""Unit tests for parkalyzer.commands.routes._route_and_save."""
from __future__ import annotations

import asyncio
import json
from asyncio import Semaphore
from unittest.mock import AsyncMock, MagicMock

import httpx

from parkalyzer.commands.routes import _route_and_save

ORS_BASE_URL = "http://localhost:8080"
PROFILE = "foot-walking"

SAMPLE_GEOMETRY = {
    "type": "LineString",
    "coordinates": [[8.8, 53.1], [8.85, 53.15], [8.9, 53.2]],
}

SAMPLE_ORS_RESPONSE = {
    "routes": [
        {
            "summary": {"distance": 1234.5, "duration": 987.6},
            "geometry": SAMPLE_GEOMETRY,
        }
    ]
}

_CALL_ARGS = dict(
    gitter_id="100mN53100E8800",
    census_lat=53.1,
    census_lon=8.8,
    park_id=42,
    park_lat=53.2,
    park_lon=8.9,
    ors_url=ORS_BASE_URL,
    profile=PROFILE,
)


def _make_pool():
    """Return (pool, mock_cur) where pool supports async with pool.connection() as conn.

    pool.connection() and conn.cursor() are synchronous calls returning async CMs.
    Using MagicMock (not AsyncMock) for conn so that conn.cursor() returns the CM
    synchronously rather than as a coroutine.
    """
    mock_cur = AsyncMock()

    cursor_cm = MagicMock()
    cursor_cm.__aenter__ = AsyncMock(return_value=mock_cur)
    cursor_cm.__aexit__ = AsyncMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.cursor.return_value = cursor_cm

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.connection.return_value = conn_cm

    return pool, mock_cur


def _make_response(status_code: int, body=None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = body
    response.text = str(body)
    return response


def _run(pool, status_code, body=None, task_id=1):
    """Helper: run _route_and_save with a given ORS response."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = _make_response(status_code, body)
    progress = MagicMock()
    asyncio.run(
        _route_and_save(
            pool, mock_client, Semaphore(1), progress, task_id, **_CALL_ARGS
        )
    )
    return mock_client, progress


def test_route_and_save_sends_geojson_format():
    """ORS request must include geometry_format=geojson."""
    pool, _ = _make_pool()
    mock_client, _ = _run(pool, 200, SAMPLE_ORS_RESPONSE)

    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert payload.get("geometry_format") == "geojson"


def test_route_and_save_inserts_geometry():
    """The GeoJSON geometry string must be the 5th parameter passed to cur.execute."""
    pool, mock_cur = _make_pool()
    _run(pool, 200, SAMPLE_ORS_RESPONSE)

    assert mock_cur.execute.called
    params = mock_cur.execute.call_args.args[1]
    geometry_json = params[4]
    assert isinstance(geometry_json, str)
    parsed = json.loads(geometry_json)
    assert parsed["type"] == "LineString"
    assert parsed["coordinates"] == SAMPLE_GEOMETRY["coordinates"]


def test_route_and_save_inserts_distance_and_duration():
    """Distance and duration from ORS summary are stored at params[2] and params[3]."""
    pool, mock_cur = _make_pool()
    _run(pool, 200, SAMPLE_ORS_RESPONSE)

    params = mock_cur.execute.call_args.args[1]
    assert params[2] == 1234.5
    assert params[3] == 987.6


def test_route_and_save_sentinel_on_ors_error():
    """A non-200 response causes a sentinel row (NULL, NULL, NULL) to be inserted."""
    pool, mock_cur = _make_pool()
    _run(pool, 500)

    assert mock_cur.execute.called
    sql = mock_cur.execute.call_args.args[0]
    assert "NULL" in sql


def test_route_and_save_advances_progress():
    """progress.advance must be called with the task_id even on ORS error."""
    pool, _ = _make_pool()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = _make_response(500)
    progress = MagicMock()
    task_id = 7

    asyncio.run(
        _route_and_save(
            pool, mock_client, Semaphore(1), progress, task_id, **_CALL_ARGS
        )
    )

    progress.advance.assert_called_once_with(task_id)

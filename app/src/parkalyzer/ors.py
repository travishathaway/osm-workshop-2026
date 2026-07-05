from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from parkalyzer.constants import ORS_DEFAULT_PROFILE, ORS_MATRIX_PATH
from parkalyzer.errors import ORSError, ORSResponseError, ORSTimeoutError


@dataclass
class MatrixResult:
    """Result from an ORS /v2/matrix call.

    Attributes:
        durations: 2-D list [source_i][dest_j] → travel time in seconds (None if unroutable).
        distances: 2-D list [source_i][dest_j] → distance in meters (None if unroutable).
        sources: ORS-resolved source snap points.
        destinations: ORS-resolved destination snap points.
    """

    durations: list[list[float | None]]
    distances: list[list[float | None]]
    sources: list[dict] = field(default_factory=list)
    destinations: list[dict] = field(default_factory=list)


class ORSClient:
    """Synchronous ORS API client (context manager).

    Usage::

        with ORSClient(base_url="http://localhost:8080") as client:
            result = client.matrix(
                locations=[(13.405, 52.520), (13.389, 52.517)],
                sources=[0],
                destinations=[1],
            )
    """

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def matrix(
        self,
        locations: list[tuple[float, float]],
        profile: str = ORS_DEFAULT_PROFILE,
        sources: list[int] | None = None,
        destinations: list[int] | None = None,
        metrics: list[str] | None = None,
    ) -> MatrixResult:
        """Call the ORS /v2/matrix endpoint.

        Args:
            locations: (longitude, latitude) pairs in WGS84.
            profile: ORS routing profile.
            sources: Indices into ``locations`` to use as origins.
            destinations: Indices into ``locations`` to use as targets.
            metrics: Metrics to return. Defaults to ["duration", "distance"].

        Raises:
            ORSTimeoutError: If the request times out.
            ORSResponseError: If ORS returns a non-200 response.
            ORSError: For other HTTP transport failures.
        """
        if metrics is None:
            metrics = ["duration", "distance"]

        url = self.base_url + ORS_MATRIX_PATH.format(profile=profile)
        payload: dict = {
            "locations": [[lon, lat] for lon, lat in locations],
            "metrics": metrics,
        }
        if sources is not None:
            payload["sources"] = sources
        if destinations is not None:
            payload["destinations"] = destinations

        try:
            response = self._client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ORSTimeoutError(f"ORS request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ORSError(f"ORS request failed: {exc}") from exc

        if response.status_code != 200:
            raise ORSResponseError(response.status_code, response.text)

        data = response.json()
        return MatrixResult(
            durations=data.get("durations", []),
            distances=data.get("distances", []),
            sources=data.get("sources", []),
            destinations=data.get("destinations", []),
        )

    def health_check(self) -> bool:
        """Return True if the ORS instance is reachable and reports healthy."""
        try:
            response = self._client.get(self.base_url + "/ors/v2/health", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ORSClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

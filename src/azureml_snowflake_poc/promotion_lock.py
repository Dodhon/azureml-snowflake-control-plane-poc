"""Azure Blob lease serialization for batch-endpoint promotion."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from functools import wraps
from time import monotonic, sleep
from typing import Any, ParamSpec, TypeVar
from urllib.parse import urlparse

_P = ParamSpec("_P")
_R = TypeVar("_R")


def acquire_lease(
    client: Any,
    *,
    lease_conflict_error: type[Exception],
    timeout_seconds: float = 900,
    poll_seconds: float = 5,
    clock: Callable[[], float] = monotonic,
    wait: Callable[[float], None] = sleep,
) -> Any:
    """Wait for one active lease to clear, propagating non-conflict failures."""
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("lease timeout and poll interval must be positive")
    deadline = clock() + timeout_seconds
    while True:
        try:
            return client.acquire_lease(lease_duration=-1)
        except lease_conflict_error as error:
            if (
                getattr(error, "status_code", None) != 409
                or getattr(error, "error_code", None) != "LeaseAlreadyPresent"
            ):
                raise
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for the active promotion lease") from error
            wait(min(poll_seconds, remaining))


@contextmanager
def blob_lease(
    client: Any,
    *,
    resource_exists_error: type[Exception],
    lease_conflict_error: type[Exception],
) -> Iterator[None]:
    """Hold one infinite blob lease and release it after the protected operation.

    The lock blob is created idempotently. A process crash leaves the infinite
    lease in place, so an operator must break it before retrying promotion.
    """
    with suppress(resource_exists_error):
        client.upload_blob(b"", overwrite=False)
    lease = acquire_lease(client, lease_conflict_error=lease_conflict_error)
    try:
        yield
    finally:
        lease.release()


@contextmanager
def azure_blob_promotion_lock(blob_url: str) -> Iterator[None]:
    """Serialize endpoint promotion through a managed-identity Blob lease."""
    parsed = urlparse(blob_url)
    if parsed.scheme != "https" or not parsed.netloc or len(parsed.path.strip("/").split("/")) < 2:
        raise ValueError("promotion lock must be an HTTPS Azure Blob URL")
    if parsed.query or parsed.fragment:
        raise ValueError("promotion lock URL must not contain credentials, query, or fragment")

    from azure.core.exceptions import HttpResponseError, ResourceExistsError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobClient

    client = BlobClient.from_blob_url(blob_url, credential=DefaultAzureCredential())
    with blob_lease(
        client,
        resource_exists_error=ResourceExistsError,
        lease_conflict_error=HttpResponseError,
    ):
        yield


def serialized_promotion(method: Callable[_P, _R]) -> Callable[_P, _R]:
    """Wrap an Azure ML gateway mutation in its configured promotion lease."""

    @wraps(method)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        owner = args[0] if args else None
        blob_url = getattr(owner, "_promotion_lock_blob_url", None)
        if not isinstance(blob_url, str) or not blob_url:
            raise RuntimeError("Azure ML promotion lock Blob URL is not configured")
        with azure_blob_promotion_lock(blob_url):
            return method(*args, **kwargs)

    return wrapped

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

import azureml_snowflake_poc.promotion_lock as promotion_lock
from azureml_snowflake_poc.aml_gateway import AzureMLGateway
from azureml_snowflake_poc.promotion_lock import acquire_lease, blob_lease, serialized_promotion


class ResourceExists(Exception):
    pass


class LeaseConflict(Exception):
    status_code = 409
    error_code = "LeaseAlreadyPresent"


class FakeLease:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class FakeBlob:
    def __init__(self, *, exists: bool = False, conflicts: int = 0) -> None:
        self.exists = exists
        self.conflicts = conflicts
        self.lease = FakeLease()
        self.lease_duration: int | None = None

    def upload_blob(self, value: bytes, *, overwrite: bool) -> None:
        assert value == b""
        assert overwrite is False
        if self.exists:
            raise ResourceExists

    def acquire_lease(self, *, lease_duration: int) -> FakeLease:
        if self.conflicts:
            self.conflicts -= 1
            raise LeaseConflict
        self.lease_duration = lease_duration
        return self.lease


@pytest.mark.parametrize("exists", [False, True])
def test_blob_lease_serializes_existing_or_new_lock_blob(exists: bool) -> None:
    blob = FakeBlob(exists=exists)

    with blob_lease(
        blob,
        resource_exists_error=ResourceExists,
        lease_conflict_error=LeaseConflict,
    ):
        assert blob.lease_duration == -1
        assert blob.lease.released is False

    assert blob.lease.released is True


def test_blob_lease_releases_after_protected_failure() -> None:
    blob = FakeBlob()

    with (
        pytest.raises(RuntimeError, match="promotion failed"),
        blob_lease(
            blob,
            resource_exists_error=ResourceExists,
            lease_conflict_error=LeaseConflict,
        ),
    ):
        raise RuntimeError("promotion failed")

    assert blob.lease.released is True


def test_acquire_lease_waits_for_active_holder() -> None:
    blob = FakeBlob(conflicts=2)
    delays: list[float] = []

    lease = acquire_lease(
        blob,
        lease_conflict_error=LeaseConflict,
        timeout_seconds=30,
        poll_seconds=5,
        clock=lambda: 0,
        wait=delays.append,
    )

    assert lease is blob.lease
    assert delays == [5, 5]


def test_acquire_lease_propagates_unrelated_storage_conflict() -> None:
    class OtherConflict(Exception):
        status_code = 409
        error_code = "BlobImmutableDueToPolicy"

    class OtherBlob:
        def acquire_lease(self, *, lease_duration: int) -> None:
            assert lease_duration == -1
            raise OtherConflict

    with pytest.raises(OtherConflict):
        acquire_lease(OtherBlob(), lease_conflict_error=OtherConflict)


def test_real_promotion_gateway_fails_closed_without_lock_configuration() -> None:
    gateway = AzureMLGateway(object())

    with pytest.raises(RuntimeError, match="promotion lock Blob URL"):
        gateway.register_and_select(
            model_path=Path("."),
            model_name="quantity-model",
            candidate_version="2",
            candidate_metrics={},
            metadata={},
            rules=(),
            endpoint_name="quantity-batch",
            compute_name="cpu",
            environment_name="runtime",
            scoring_code=Path("."),
        )


def test_serialized_promotion_uses_configured_blob_url(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[str] = []

    @contextmanager
    def fake_lock(blob_url: str):
        observed.append(blob_url)
        yield

    monkeypatch.setattr(promotion_lock, "azure_blob_promotion_lock", fake_lock)

    class Gateway:
        _promotion_lock_blob_url = "https://account.blob.core.windows.net/locks/endpoint.lock"

        @serialized_promotion
        def mutate(self) -> str:
            return "updated"

    assert Gateway().mutate() == "updated"
    assert observed == ["https://account.blob.core.windows.net/locks/endpoint.lock"]

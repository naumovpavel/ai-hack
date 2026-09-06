import pytest

from interview_api.workflow.errors import WorkflowProviderError
from interview_api.workflow.storage import S3ObjectStorage


class StorageClient:
    def __init__(self):
        self.listed = []
        self.deleted = []
        self.errors = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, **kwargs):
        self.listed.append(kwargs)
        prefix = kwargs["Prefix"]
        yield {"Contents": [{"Key": f"{prefix}{number}.webm"} for number in range(1001)]}
        yield {"Contents": [{"Key": f"{prefix}last.webm"}]}

    def delete_objects(self, **kwargs):
        self.deleted.append(kwargs)
        return {"Errors": self.errors}


@pytest.mark.asyncio
async def test_delete_scopes_listing_and_batches_every_page_of_owned_objects():
    client = StorageClient()
    storage = S3ObjectStorage(client, bucket="private")
    await storage.delete_owned_objects(
        keys=("candidate-drafts/one/resume.pdf",),
        prefixes=("candidates/one/practice/attempt/",),
    )
    assert client.listed == [{"Bucket": "private", "Prefix": "candidates/one/practice/attempt/"}]
    batches = [batch["Delete"]["Objects"] for batch in client.deleted]
    assert [len(batch) for batch in batches] == [1000, 3]
    keys = {item["Key"] for batch in batches for item in batch}
    assert "candidate-drafts/one/resume.pdf" in keys
    assert "candidates/one/practice/attempt/last.webm" in keys
    assert all(
        key.startswith("candidates/one/practice/attempt/")
        or key == "candidate-drafts/one/resume.pdf"
        for key in keys
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["candidates/", "candidates//", "shared/", "candidates/one/../"])
async def test_delete_rejects_unbounded_or_unsafe_prefix_before_storage_request(prefix):
    client = StorageClient()
    with pytest.raises(ValueError):
        await S3ObjectStorage(client, bucket="private").delete_owned_objects(
            keys=(), prefixes=(prefix,)
        )
    assert client.listed == []
    assert client.deleted == []


@pytest.mark.asyncio
async def test_partial_object_deletion_failure_is_not_silently_accepted():
    client = StorageClient()
    client.errors = [{"Key": "private", "Code": "AccessDenied"}]
    with pytest.raises(WorkflowProviderError):
        await S3ObjectStorage(client, bucket="private").delete_owned_objects(
            keys=("candidate-drafts/one/resume.pdf",),
            prefixes=(),
        )

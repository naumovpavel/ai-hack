"""Verify actual MinIO/S3 signed HTTP Range and CORS before enabling integrity.

Run against the Compose public endpoint using configured S3 credentials; the
only write is a uniquely named test object, deleted even if a check fails.
"""
import asyncio
from uuid import uuid4

import boto3
import urllib3
from botocore.config import Config

from interview_api.config import Settings
from interview_api.workflow.storage import S3ObjectStorage


async def main():
    settings = Settings()
    if not settings.s3_access_key or not settings.s3_secret_key:
        raise SystemExit("Set S3_ACCESS_KEY and S3_SECRET_KEY in the environment/.env")
    client = boto3.client("s3", endpoint_url=settings.s3_public_base_url,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    storage = S3ObjectStorage(client, bucket=settings.s3_bucket)
    key = f"candidates/integrity-storage-smoke/{uuid4()}/range.mp4"
    data = bytes(range(256)) * 32
    http = urllib3.PoolManager()
    try:
        await storage.put_bytes(key, data, content_type="video/mp4")
        url = await storage.presign_download(key, filename="range.mp4", inline=True,
                                            expires_seconds=60)
        origin = settings.cors_origin_list[0]
        preflight = http.request("OPTIONS", url, headers={"Origin": origin,
            "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "range"})
        assert preflight.status in {200, 204}, "CORS preflight failed"
        assert preflight.headers.get("Access-Control-Allow-Origin") in {origin, "*"}
        result = http.request("GET", url, headers={"Range": "bytes=128-255", "Origin": origin})
        assert result.status == 206, "Storage did not honor HTTP Range"
        assert result.data == data[128:256], "Range bytes differ"
        assert result.headers.get("Content-Range") == f"bytes 128-255/{len(data)}"
        assert result.headers.get("Accept-Ranges") == "bytes"
        assert result.headers.get("Access-Control-Allow-Origin") in {origin, "*"}
        exposed = result.headers.get("Access-Control-Expose-Headers", "").lower()
        assert "content-range" in exposed or exposed == "*", "Content-Range is not exposed"
        invalid = http.request("GET", url, headers={"Range": "bytes=99999-"})
        assert invalid.status == 416, "Invalid range did not return 416"
        print("PASS: signed MinIO/S3 URLs, Range 206/416, exact bytes, CORS preflight and headers")
    finally:
        await storage.delete_owned_objects(keys=(key,), prefixes=())
        client.close()
        http.clear()


if __name__ == "__main__":
    asyncio.run(main())

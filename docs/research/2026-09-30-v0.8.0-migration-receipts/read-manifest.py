"""Run inside the API image to record hashes and metadata, without content or secrets."""

import asyncio
import hashlib
import json
import os

import aioboto3
from botocore.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one()
        files = [
            dict(r)
            for r in (
                await connection.execute(
                    text(
                        "SELECT storage_path, hash_sha256, size_bytes, deleted_at IS NOT NULL AS soft_deleted FROM files ORDER BY storage_path"
                    )
                )
            ).mappings()
        ]
        exports = [
            dict(r)
            for r in (
                await connection.execute(
                    text(
                        "SELECT storage_key, status, expires_at > now() AS unexpired FROM user_export_jobs ORDER BY storage_key"
                    )
                )
            ).mappings()
        ]
    await engine.dispose()
    async with aioboto3.Session().client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    ) as client:
        bucket = os.environ["S3_BUCKET"]
        objects = []
        listing = await client.list_objects_v2(Bucket=bucket)
        assert not listing.get("IsTruncated")
        for entry in sorted(listing.get("Contents", []), key=lambda e: e["Key"]):
            response = await client.get_object(Bucket=bucket, Key=entry["Key"])
            digest = hashlib.sha256()
            digest.update(await response["Body"].read())
            objects.append(
                {
                    "key": entry["Key"],
                    "size_bytes": entry["Size"],
                    "sha256": digest.hexdigest(),
                    "etag": response["ETag"],
                    "content_type": response["ContentType"],
                }
            )
    print(
        json.dumps(
            {"alembic_revision": revision, "files": files, "exports": exports, "objects": objects},
            indent=2,
        )
    )


asyncio.run(main())

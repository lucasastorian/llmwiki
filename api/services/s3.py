import json
import logging

import aioboto3
from config import settings

logger = logging.getLogger(__name__)


class S3Service:
    def __init__(self):
        self._session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        self._bucket = settings.S3_BUCKET

    async def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        async with self._session.client("s3") as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    async def upload_file(self, key: str, file_path: str, content_type: str = "application/octet-stream"):
        # aioboto3's transfer helper streams from disk and automatically uses
        # multipart upload for large files. Do not materialize a 100 MB TUS
        # upload as one Python bytes object before sending it to S3.
        async with self._session.client("s3") as s3:
            await s3.upload_file(
                file_path,
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )

    async def generate_presigned_get(self, key: str, expires_in: int = 3600) -> str:
        async with self._session.client("s3") as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )

    async def generate_presigned_put(self, key: str, content_type: str = "application/pdf", expires_in: int = 3600) -> str:
        async with self._session.client("s3") as s3:
            return await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_in,
            )

    async def delete_prefix(self, prefix: str) -> None:
        async with self._session.client("s3") as s3:
            paginator = s3.get_paginator("list_objects_v2")
            batch: list[dict] = []
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    batch.append({"Key": obj["Key"]})
                    if len(batch) == 1000:
                        await s3.delete_objects(Bucket=self._bucket, Delete={"Objects": batch})
                        batch = []
            if batch:
                await s3.delete_objects(Bucket=self._bucket, Delete={"Objects": batch})

    async def download_bytes(self, key: str) -> bytes:
        async with self._session.client("s3") as s3:
            resp = await s3.get_object(Bucket=self._bucket, Key=key)
            return await resp["Body"].read()

    async def download_to_file(self, key: str, file_path: str):
        async with self._session.client("s3") as s3:
            await s3.download_file(self._bucket, key, file_path)

    async def download_json(self, key: str) -> dict:
        body = await self.download_bytes(key)
        return json.loads(body)

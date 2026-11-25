"""Acesso ao bucket S3 (MinIO em dev) para áudio de lote."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any


class Storage:
    def __init__(self) -> None:
        import boto3

        from kvoice.settings import get_settings

        configuracao = get_settings()
        self._s3: Any = boto3.client(
            "s3",
            endpoint_url=configuracao.s3_endpoint_url,
            aws_access_key_id=configuracao.s3_access_key_id,
            aws_secret_access_key=configuracao.s3_secret_access_key,
            region_name="us-east-1",
        )
        self._bucket = configuracao.s3_bucket_outputs

    def _put(self, key: str, data: bytes, content_type: str) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def _presign(self, key: str, ttl_s: int) -> str:
        url: str = self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_s,
        )
        return url

    # O boto3 é síncrono: as chamadas vão para o executor para não travar o event loop.
    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._put, key, data, content_type)

    async def presigned_url(self, key: str, ttl_s: int = 86400) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._presign, key, ttl_s)


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    return Storage()

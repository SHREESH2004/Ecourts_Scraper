"""Private PDF storage using the Supabase S3-compatible API."""

import os
from functools import lru_cache
from urllib.parse import quote

from botocore.exceptions import ClientError


STORAGE_SETTINGS = {
    "endpoint_url": "SUPABASE_S3_ENDPOINT_URL",
    "region_name": "SUPABASE_S3_REGION",
    "bucket_name": "SUPABASE_S3_BUCKET",
    "aws_access_key_id": "SUPABASE_S3_ACCESS_KEY_ID",
    "aws_secret_access_key": "SUPABASE_S3_SECRET_ACCESS_KEY",
}


def _storage_configured():
    present = {
        setting: bool(os.getenv(environment_name))
        for setting, environment_name in STORAGE_SETTINGS.items()
    }
    if any(present.values()) and not all(present.values()):
        missing = [
            STORAGE_SETTINGS[setting]
            for setting, is_present in present.items()
            if not is_present
        ]
        raise RuntimeError(
            "Supabase PDF storage is partially configured; missing: "
            + ", ".join(missing)
        )
    return all(present.values())


def is_storage_configured():
    return _storage_configured()


@lru_cache(maxsize=1)
def _get_s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ[STORAGE_SETTINGS["endpoint_url"]],
        region_name=os.environ[STORAGE_SETTINGS["region_name"]],
        aws_access_key_id=os.environ[STORAGE_SETTINGS["aws_access_key_id"]],
        aws_secret_access_key=os.environ[STORAGE_SETTINGS["aws_secret_access_key"]],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def upload_pdf(file_path, object_key):
    if not _storage_configured():
        return None

    _get_s3_client().upload_file(
        file_path,
        os.environ[STORAGE_SETTINGS["bucket_name"]],
        object_key,
        ExtraArgs={"ContentType": "application/pdf"},
    )
    return object_key


def upload_pdf_bytes(pdf_content, object_key):
    if not _storage_configured():
        raise RuntimeError("Supabase PDF storage is not configured")

    _get_s3_client().put_object(
        Bucket=os.environ[STORAGE_SETTINGS["bucket_name"]],
        Key=object_key,
        Body=pdf_content,
        ContentType="application/pdf",
    )
    return object_key


def get_pdf_object_info(object_key):
    if not _storage_configured():
        return None

    try:
        result = _get_s3_client().head_object(
            Bucket=os.environ[STORAGE_SETTINGS["bucket_name"]],
            Key=object_key,
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error_code in {"404", "NoSuchKey", "NotFound"} or status_code == 404:
            return None
        raise

    return {"file_size": result.get("ContentLength", 0)}


def create_pdf_download_url(object_key, filename, download=False):
    if not _storage_configured():
        return None

    disposition = "attachment" if download else "inline"
    encoded_filename = quote(filename, safe="")
    return _get_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": os.environ[STORAGE_SETTINGS["bucket_name"]],
            "Key": object_key,
            "ResponseContentType": "application/pdf",
            "ResponseContentDisposition": (
                f"{disposition}; filename*=UTF-8''{encoded_filename}"
            ),
        },
        ExpiresIn=300,
    )

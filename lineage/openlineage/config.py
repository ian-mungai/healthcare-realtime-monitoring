import os

DEFAULT_DATA_BUCKET_NAME = "<project-data-bucket>"


def data_bucket_name() -> str:
    return os.getenv("DATA_BUCKET_NAME", DEFAULT_DATA_BUCKET_NAME)


def lineage_event_path(component: str) -> str:
    return f"s3://{data_bucket_name()}/lineage/openlineage/{component}/event"

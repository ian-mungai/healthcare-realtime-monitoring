import os


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for OpenLineage configuration")
    return value


def data_bucket_name() -> str:
    return required_env("DATA_BUCKET_NAME")


def project_namespace() -> str:
    return required_env("PROJECT_NAME")


def qualified_dataset(database_variable: str, table_variable: str) -> str:
    return f"{required_env(database_variable)}.{required_env(table_variable)}"


def lineage_event_path(component: str) -> str:
    return f"s3://{data_bucket_name()}/lineage/openlineage/{component}/event"

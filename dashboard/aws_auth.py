import os

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SERVICE_NAME = "execute-api"


def get_aws_credentials():
    credentials = boto3.Session(region_name=AWS_REGION).get_credentials()

    if credentials is None:
        raise RuntimeError("AWS credentials are not available for API authentication")

    return credentials.get_frozen_credentials()


def get_sigv4_headers(url: str) -> dict[str, str]:
    signing_url = url

    if signing_url.startswith("wss://"):
        signing_url = "https://" + signing_url.removeprefix("wss://")

    elif signing_url.startswith("ws://"):
        signing_url = "http://" + signing_url.removeprefix("ws://")

    request = AWSRequest(method="GET", url=signing_url)

    SigV4Auth(get_aws_credentials(), SERVICE_NAME, AWS_REGION).add_auth(request)

    return {key: str(value) for key, value in request.headers.items()}

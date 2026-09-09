import json
import os
from fnmatch import fnmatchcase
from typing import Any

PATIENT_ACCESS_POLICY_ENV = "PATIENT_ACCESS_POLICY"


def get_principal_arn(event: dict[str, Any]) -> str | None:
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    iam = authorizer.get("iam") or {}
    identity = request_context.get("identity") or {}

    principal_arn = iam.get("userArn") or authorizer.get("userArn") or identity.get("userArn")
    return principal_arn if isinstance(principal_arn, str) and principal_arn else None


def load_patient_access_policy() -> dict[str, list[str]]:
    raw_policy = os.getenv(PATIENT_ACCESS_POLICY_ENV, "{}")

    try:
        policy = json.loads(raw_policy)
    except json.JSONDecodeError:
        return {}

    if not isinstance(policy, dict):
        return {}

    return {
        principal_pattern: patient_patterns
        for principal_pattern, patient_patterns in policy.items()
        if isinstance(principal_pattern, str)
        and isinstance(patient_patterns, list)
        and all(isinstance(patient_pattern, str) for patient_pattern in patient_patterns)
    }


def is_patient_authorized(event: dict[str, Any], patient_id: str) -> bool:
    principal_arn = get_principal_arn(event)

    if principal_arn is None:
        return False

    for principal_pattern, patient_patterns in load_patient_access_policy().items():
        if fnmatchcase(principal_arn, principal_pattern) and any(fnmatchcase(patient_id, pattern) for pattern in patient_patterns):
            return True

    return False

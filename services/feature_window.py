"""The live feature-window table shared by the stream processor (writes) and the early-warning endpoint (reads).

One item per observation set, keyed by encounter and a sort key that orders readings by time as text: the UTC event
time with microseconds, then the observation ID. The early-warning endpoint keeps the encounter's score for each model
version in the same partition under score_key(), which sorts after every reading.
"""

from datetime import UTC, datetime

# Items expire two days after they are written; scoring needs them for the first 15 minutes of an encounter.
TTL_SECONDS = 2 * 86400
SCORE_PREFIX = "score#"


def time_key(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def reading_key(event_timestamp: str, observation_id: str) -> str:
    moment = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))
    return f"{time_key(moment if moment.tzinfo else moment.replace(tzinfo=UTC))}#{observation_id}"


def score_key(model_version: str) -> str:
    return f"{SCORE_PREFIX}{model_version}"

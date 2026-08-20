from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class FHIRWebhookEvent:
    received_at: datetime
    resource_type: str
    resource_id: str | None
    payload: dict

    def to_dict(self) -> dict:
        result = asdict(self)
        result["received_at"] = self.received_at.isoformat()

        return result
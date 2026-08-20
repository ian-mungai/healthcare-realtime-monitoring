from services.fhir_webhook.app.models import FHIRWebhookEvent


class WebhookEventStore:
    def __init__(self):
        self.events: list[FHIRWebhookEvent] = []

    def add(self, event: FHIRWebhookEvent) -> None:
        self.events.append(event)

    def list_events(self) -> list[FHIRWebhookEvent]:
        return list(self.events)

    def clear(self) -> None:
        self.events.clear()


event_store = WebhookEventStore()
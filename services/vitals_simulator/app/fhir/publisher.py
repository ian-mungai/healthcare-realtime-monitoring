from dataclasses import asdict, dataclass

from services.vitals_simulator.app.fhir.client import CreatedFHIRResource, HAPIFHIRClient
from services.vitals_simulator.app.simulation.event import SimulatorEvent


@dataclass(frozen=True)
class PublishedSimulatorEvent:
    source_record_id: str
    offset_seconds: int
    patient_id: str
    encounter_id: str
    published_count: int
    resources: list[CreatedFHIRResource]

    def to_dict(self) -> dict:
        return {
            "source_record_id": self.source_record_id,
            "offset_seconds": self.offset_seconds,
            "patient_id": self.patient_id,
            "encounter_id": self.encounter_id,
            "published_count": self.published_count,
            "resources": [asdict(resource) for resource in self.resources],
        }


def publish_simulator_event(event: SimulatorEvent, client: HAPIFHIRClient) -> PublishedSimulatorEvent:
    created_resources = []

    for observation in event.observations:
        created_resource = client.post_resource(observation)
        created_resources.append(created_resource)

    return PublishedSimulatorEvent(
        source_record_id=event.source_record_id,
        offset_seconds=event.offset_seconds,
        patient_id=event.patient_id,
        encounter_id=event.encounter_id,
        published_count=len(created_resources),
        resources=created_resources,
    )

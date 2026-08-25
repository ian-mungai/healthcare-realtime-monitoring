from services.vitals_simulator.app.fhir.client import CreatedFHIRResource
from services.vitals_simulator.app.fhir.publisher import publish_simulator_event
from services.vitals_simulator.app.simulation.event import SimulatorEvent


class FakeFHIRClient:
    def __init__(self):
        self.resources = []

    def post_resource(self, resource: dict) -> CreatedFHIRResource:
        self.resources.append(resource)
        resource_id = f"observation_{len(self.resources)}"

        return CreatedFHIRResource(resource_type="Observation", resource_id=resource_id, location=f"Observation/{resource_id}", status_code=201)


def test_publish_simulator_event():
    event = SimulatorEvent(
        source_record_id="bidmc01n",
        offset_seconds=1,
        patient_id="patient_123",
        encounter_id="encounter_456",
        observation_count=3,
        observations=[
            {"resourceType": "Observation", "status": "final"},
            {"resourceType": "Observation", "status": "final"},
            {"resourceType": "Observation", "status": "final"},
        ],
    )

    client = FakeFHIRClient()
    result = publish_simulator_event(event, client)

    assert result.published_count == 3
    assert len(result.resources) == 3
    assert len(client.resources) == 3
    assert result.resources[0].resource_id == "observation_1"

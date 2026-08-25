from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SimulatorEvent:
    source_record_id: str
    offset_seconds: int
    patient_id: str
    encounter_id: str
    observation_count: int
    observations: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)

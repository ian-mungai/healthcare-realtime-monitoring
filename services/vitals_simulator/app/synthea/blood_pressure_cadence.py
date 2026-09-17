from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading

DEFAULT_BP_INTERVAL_SECONDS = 300


class BloodPressureCadence:
    def __init__(self, readings: list[BloodPressureReading], interval_seconds: int = DEFAULT_BP_INTERVAL_SECONDS):
        if not readings:
            raise ValueError("At least one blood pressure reading is required")

        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")

        self.readings = readings
        self.interval_seconds = interval_seconds
        self.reading_index = 0
        self.last_emitted_interval = -1

    def is_due(self, offset_seconds: int) -> bool:
        return offset_seconds % self.interval_seconds == 0

    def get_reading(self, elapsed_seconds: float) -> BloodPressureReading | None:
        if 0 < elapsed_seconds < self.interval_seconds:
            return None

        interval = int(elapsed_seconds // self.interval_seconds)
        if interval <= self.last_emitted_interval:
            return None

        reading = self.readings[self.reading_index]
        self.reading_index = (self.reading_index + 1) % len(self.readings)
        self.last_emitted_interval = interval

        return reading

    def reset(self) -> None:
        self.reading_index = 0
        self.last_emitted_interval = -1

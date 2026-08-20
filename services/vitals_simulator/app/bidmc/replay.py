import time
from collections.abc import Iterator

from services.vitals_simulator.app.bidmc.source import (
    VitalReading,
)


class BIDMCReplay:
    def __init__(
        self,
        readings: list[VitalReading],
        replay_speed: float = 1.0,
    ) -> None:
        if replay_speed < 0:
            raise ValueError(
                "replay_speed cannot be negative"
            )

        self.readings = sorted(
            readings,
            key=lambda reading:
                reading.offset_seconds,
        )

        self.replay_speed = replay_speed

    def __iter__(
        self,
    ) -> Iterator[VitalReading]:
        previous_offset = None

        for reading in self.readings:
            if (
                previous_offset is not None
                and self.replay_speed > 0
            ):
                source_delta = (
                    reading.offset_seconds
                    - previous_offset
                )

                delay = (
                    source_delta
                    / self.replay_speed
                )

                if delay > 0:
                    time.sleep(delay)

            yield reading

            previous_offset = (
                reading.offset_seconds
            )
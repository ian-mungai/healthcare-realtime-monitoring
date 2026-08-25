from fastapi import FastAPI, HTTPException

from services.vitals_simulator.app.bidmc.source import SUPPORTED_RECORD_MAX, SUPPORTED_RECORD_MIN, fetch_remote_bidmc_record

app = FastAPI(title="BIDMC Vitals Source API", version="1.0.0")


_record_cache: dict[int, list] = {}
_record_position: dict[int, int] = {}


def get_record(record_number: int):
    if record_number not in _record_cache:
        try:
            _record_cache[record_number] = fetch_remote_bidmc_record(record_number)

        except Exception as exc:
            raise HTTPException(status_code=502, detail=(f"Unable to retrieve BIDMC record {record_number} from PhysioNet: {exc}")) from exc

    return _record_cache[record_number]


@app.get("/health")
def health():
    return {"status": "ok", "source": "PhysioNet BIDMC"}


@app.get("/records")
def list_records():
    return {
        "minimum": SUPPORTED_RECORD_MIN,
        "maximum": SUPPORTED_RECORD_MAX,
        "records": [f"bidmc{number:02d}" for number in range(SUPPORTED_RECORD_MIN, SUPPORTED_RECORD_MAX + 1)],
    }


@app.get("/records/{record_number}")
def get_record_info(record_number: int):
    try:
        readings = get_record(record_number)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "record_number": record_number,
        "source_record_id": (readings[0].source_record_id if readings else None),
        "reading_count": len(readings),
        "first_reading": (readings[0].to_dict() if readings else None),
    }


@app.get("/records/{record_number}/next")
def get_next_reading(record_number: int):
    try:
        readings = get_record(record_number)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not readings:
        raise HTTPException(status_code=404, detail="No BIDMC readings available")

    position = _record_position.get(record_number, 0)

    if position >= len(readings):
        position = 0

    reading = readings[position]

    _record_position[record_number] = position + 1

    return reading.to_dict()


@app.post("/records/{record_number}/reset")
def reset_record(record_number: int):
    _record_position[record_number] = 0

    return {"record_number": record_number, "position": 0}

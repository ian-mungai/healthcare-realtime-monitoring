from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from services.fhir_webhook.app.kinesis.client import KinesisPublisher, KinesisPublisherError
from services.fhir_webhook.app.parser import InvalidFHIRPayloadError, parse_fhir_payload
from services.fhir_webhook.app.security import WEBHOOK_SECRET_HEADER, validate_webhook_secret

app = FastAPI(title="FHIR Observation Webhook", version="0.2.0")


@app.get("/health")
def health() -> dict:
    return {"status": "healthy", "service": "fhir_webhook"}


@app.post("/webhooks/fhir")
async def receive_fhir_webhook(request: Request, x_webhook_secret: str | None = Header(default=None, alias=WEBHOOK_SECRET_HEADER)) -> JSONResponse:  # noqa: E501
    try:
        payload = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="Request body must contain valid JSON") from error

    if not validate_webhook_secret(x_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        event = parse_fhir_payload(payload)
    except InvalidFHIRPayloadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        publisher = KinesisPublisher()
        result = publisher.publish(event)
    except KinesisPublisherError as error:
        raise HTTPException(status_code=503, detail="Kinesis ingestion failed") from error

    return JSONResponse(status_code=202, content={"status": "accepted", "resource_type": event.resource_type, "resource_id": event.resource_id, "shard_id": result.shard_id, "sequence_number": result.sequence_number})

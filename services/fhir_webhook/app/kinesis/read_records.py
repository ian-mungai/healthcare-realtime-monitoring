import json
import os
import time
from pathlib import Path

import boto3

OUTPUT_FILE = Path("services/fhir_webhook/output/kinesis_decoded_records.json")
MAX_READ_ATTEMPTS = 20
READ_DELAY_SECONDS = 0.5


def main():
    stream_name = os.getenv("KINESIS_STREAM_NAME")
    region_name = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")

    if not stream_name:
        raise RuntimeError("KINESIS_STREAM_NAME is not configured")

    if not region_name:
        raise RuntimeError("AWS_REGION is not configured")

    client = boto3.client("kinesis", region_name=region_name)
    shards = client.list_shards(StreamName=stream_name).get("Shards", [])

    if not shards:
        raise RuntimeError("Kinesis stream contains no shards")

    decoded_records = []

    for shard in shards:
        shard_id = shard["ShardId"]

        iterator_response = client.get_shard_iterator(StreamName=stream_name, ShardId=shard_id, ShardIteratorType="TRIM_HORIZON")

        shard_iterator = iterator_response["ShardIterator"]

        for attempt in range(1, MAX_READ_ATTEMPTS + 1):
            response = client.get_records(ShardIterator=shard_iterator, Limit=100)

            for record in response.get("Records", []):
                payload = json.loads(record["Data"].decode("utf-8"))

                decoded_records.append(
                    {
                        "shard_id": shard_id,
                        "sequence_number": record["SequenceNumber"],
                        "partition_key": record["PartitionKey"],
                        "approximate_arrival_timestamp": record["ApproximateArrivalTimestamp"].isoformat(),
                        "payload": payload,
                    }
                )

            shard_iterator = response.get("NextShardIterator")

            print(f"shard={shard_id} attempt={attempt} records={len(response.get('Records', []))} millis_behind_latest={response.get('MillisBehindLatest')}")

            if not shard_iterator:
                break

            if response.get("MillisBehindLatest") == 0 and decoded_records:
                break

            time.sleep(READ_DELAY_SECONDS)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(decoded_records, file, indent=2)

    print()
    print(f"Records found: {len(decoded_records)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

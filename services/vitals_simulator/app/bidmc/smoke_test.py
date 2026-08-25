from services.vitals_simulator.app.bidmc.source import fetch_remote_bidmc_record


def main():
    print("Testing remote PhysioNet BIDMC connection...")

    readings = fetch_remote_bidmc_record(1)

    if not readings:
        raise RuntimeError("PhysioNet returned no BIDMC readings")

    print()
    print(f"Remote readings loaded: {len(readings)}")

    print()
    print("First 5 readings:")

    for reading in readings[:5]:
        print(reading.to_dict())

    print()
    print("Remote PhysioNet BIDMC connection verified successfully.")


if __name__ == "__main__":
    main()

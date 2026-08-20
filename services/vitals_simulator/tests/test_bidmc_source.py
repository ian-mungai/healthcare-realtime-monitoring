import numpy as np
import pytest

from services.vitals_simulator.app.bidmc.source import (
    build_record_name,
    find_channel_index,
    normalize_channel_name,
    normalize_optional_float,
)


def test_build_record_name():
    assert (
        build_record_name(1)
        == "bidmc01n"
    )

    assert (
        build_record_name(53)
        == "bidmc53n"
    )


def test_invalid_record_number():
    with pytest.raises(
        ValueError,
    ):
        build_record_name(0)

    with pytest.raises(
        ValueError,
    ):
        build_record_name(54)


def test_normalize_optional_float():
    assert (
        normalize_optional_float(
            94.0
        )
        == 94.0
    )

    assert (
        normalize_optional_float(
            np.nan
        )
        is None
    )


def test_normalize_channel_name():
    assert (
        normalize_channel_name("HR,")
        == "HR"
    )

    assert (
        normalize_channel_name("RESP,")
        == "RESP"
    )

    assert (
        normalize_channel_name("SpO2,")
        == "SPO2"
    )

    assert (
        normalize_channel_name(" HR, ")
        == "HR"
    )


def test_find_channel_index_with_bidmc_names():
    signal_names = [
        "HR,",
        "PULSE,",
        "RESP,",
        "SpO2,",
    ]

    assert (
        find_channel_index(
            signal_names,
            {"HR"},
        )
        == 0
    )

    assert (
        find_channel_index(
            signal_names,
            {"RESP", "RR"},
        )
        == 2
    )

    assert (
        find_channel_index(
            signal_names,
            {"SPO2"},
        )
        == 3
    )
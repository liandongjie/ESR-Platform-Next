from app.gis.indicators import INDICATORS, get_indicator, legacy_default_weights


def test_indicator_catalog_contains_exactly_twelve_business_indicators():
    assert len(INDICATORS) == 12
    assert {indicator.filename for indicator in INDICATORS} == {
        "AQI.tif",
        "fmts.tif",
        "fmyl.tif",
        "gyfb.tif",
        "hwmd.tif",
        "jmdmd.tif",
        "NDVI.tif",
        "PM25.tif",
        "rkmd.tif",
        "xspb.tif",
        "xsqs.tif",
        "xxmd.tif",
    }


def test_legacy_default_selection_and_weights_are_preserved():
    weights = legacy_default_weights()

    assert weights == {"PM25": 30.0, "AQI": 40.0, "NDVI": 30.0}
    assert sum(weights.values()) == 100.0


def test_get_indicator_uses_stable_legacy_business_key():
    indicator = get_indicator("rkmd")

    assert indicator.name == "人口密度"
    assert indicator.filename == "rkmd.tif"

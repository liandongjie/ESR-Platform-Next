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
    assert [indicator.category for indicator in INDICATORS] == [
        "environment",
        "environment",
        "environment",
        "environment",
        "population",
        "population",
        "population",
        "social",
        "social",
        "social",
        "social",
        "social",
    ]
    assert {indicator.risk_direction for indicator in INDICATORS} == {"increasing"}
    assert {indicator.code: indicator.risk_semantics for indicator in INDICATORS} == {
        "PM25": "PM2.5 值越高，背景空气污染与健康暴露敏感性越高。",
        "AQI": "AQI 值越高，背景空气污染压力与选址环境风险越高。",
        "NDVI": "NDVI 值越高，植被生态敏感性越高，设施扰动风险越高。",
        "hwmd": "河网密度越高，水环境受影响与污染扩散敏感性越高。",
        "rkmd": "人口密度越高，潜在暴露人口与邻避冲突敏感性越高。",
        "xxmd": "学校密度越高，敏感人群和公共设施受影响风险越高。",
        "jmdmd": "居民点密度越高，居民暴露与邻避冲突敏感性越高。",
        "xspb": "刑事批捕率越高，区域社会治安与稳定风险压力越高。",
        "xsqs": "刑事起诉率越高，区域社会治安与稳定风险压力越高。",
        "gyfb": "官员腐败指数越高，治理失效与项目社会风险越高。",
        "fmyl": "垃圾焚烧负面舆论占比越高，公众反对与舆情风险越高。",
        "fmts": "环境投诉负面数量占比越高，环境冲突与社会敏感性越高。",
    }


def test_legacy_default_selection_and_weights_are_preserved():
    weights = legacy_default_weights()

    assert weights == {"PM25": 30.0, "AQI": 40.0, "NDVI": 30.0}
    assert sum(weights.values()) == 100.0


def test_get_indicator_uses_stable_legacy_business_key():
    indicator = get_indicator("rkmd")

    assert indicator.name == "人口密度"
    assert indicator.filename == "rkmd.tif"

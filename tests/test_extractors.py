from debug_single_pw import extract_area_from_text, extract_location_from_jsonld


def test_extract_location_from_jsonld_name() -> None:
    data = {"location": {"name": "Київ"}}
    assert extract_location_from_jsonld(data) == "Київ"


def test_extract_location_from_jsonld_address() -> None:
    data = {"address": {"addressLocality": "Львів", "addressRegion": "Львівська область"}}
    assert extract_location_from_jsonld(data) == "Львів, Львівська область"


def test_extract_location_from_jsonld_area_served() -> None:
    data = {"areaServed": {"name": "Харків"}}
    assert extract_location_from_jsonld(data) == "Харків"


def test_extract_area_from_text_sqm() -> None:
    assert extract_area_from_text("Площа 120 м²") == 120


def test_extract_area_from_text_ignores_sotka() -> None:
    assert extract_area_from_text("Ділянка 6 соток біля міста") is None

from copy import deepcopy

import pytest

from domain.item import ItemsResponse
from engine.catalog_snapshots import extract_catalog
from scripts.retrieve_ad_links import extract_item_links


@pytest.mark.parametrize("wrap", [lambda c: c, lambda c: {"catalog": c},
                                  lambda c: {"result": c}, lambda c: {"result": {"catalog": c}}])
def test_combined_catalog_skips_blocks_deduplicates_and_preserves_original(wrap):
    catalog = {
        "items": [{"id": 1, "title": "Main", "type": "item"}],
        "extraBlockItems": [
            {"type": "section", "title": "Другие города"}, None,
            {"id": 987, "type": "banner"}, {"id": True}, {"id": 0},
            {"id": -1}, {"id": "banner"}, {"id": {"value": False}},
            {"id": "1", "title": "Duplicate"},
            {"id": "2", "title": "Extra", "urlPath": "/board_2"},
            {"id": {"value": "3"}, "title": "Wrapped ID"}, {"id": 2},
        ],
    }
    payload = wrap(catalog)
    original = deepcopy(payload)
    result = extract_catalog(payload)
    ads = ItemsResponse(**result).items
    assert [ad.id for ad in ads] == [1, 2, 3]
    assert ads[0].title == "Main"
    links = extract_item_links(payload)
    assert [link["id"] for link in links] == [1, 2, 3]
    assert links[1]["api_url"] == "https://m.avito.ru/api/1/card/items/2"
    assert payload == original


@pytest.mark.parametrize("main", [{}, {"items": []}, {"items": None}])
def test_extra_items_are_used_even_without_main_items(main):
    catalog = {**main, "extraBlockItems": [{"id": 42}]}
    assert [item["id"] for item in extract_catalog({"catalog": catalog})["items"]] == [42]


def test_service_only_page_is_empty_and_unknown_structure_remains_invalid():
    assert extract_catalog({"catalog": {"extraBlockItems": [{"type": "header"}]}})["items"] == []
    assert extract_catalog({"error": "unknown response"}) == {}

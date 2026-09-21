import json
import pytest
from pathlib import Path
from watcher.apple import (
    normalize, discover_products, select_watched, DiscoveryError,
    Product, Store, PartAvailability, parse_pickup, check_canary,
    ImplausibleResponse,
)

FIXTURES = Path(__file__).parent / "fixtures"
CANARY = "MJQ34LL/A"
WATCHED = ["MJW44LL/A", "MJW54LL/A", "MJW64LL/A", "MJW74LL/A"]


def buypage_html() -> str:
    return "<html><script>var x = " + (
        FIXTURES / "buypage_product_array.json"
    ).read_text() + ";</script></html>"


def pickup_payload():
    return json.loads(
        (FIXTURES / "pickup_message_watched_unavailable_canary_ok.json").read_text()
    )


def product_map():
    names = {
        CANARY: "iPhone 18 Pro 256GB Black",
        "MJW44LL/A": "iPhone 18 Pro Max 256GB Black",
        "MJW54LL/A": "iPhone 18 Pro Max 256GB Silver",
        "MJW64LL/A": "iPhone 18 Pro Max 256GB Burgundy",
        "MJW74LL/A": "iPhone 18 Pro Max 256GB Glacier",
    }
    return {k: Product(k, v, 1299.0) for k, v in names.items()}


# ---------- discovery ----------

def test_normalize_collapses_nbsp():
    assert normalize("iPhone 18 Pro Max") == "iPhone 18 Pro Max"


def test_discovers_all_products():
    products = discover_products(buypage_html())
    assert len(products) == 32
    assert all(p.part.endswith("LL/A") for p in products)


def test_discovered_names_are_normalized():
    assert all(" " not in p.name for p in discover_products(buypage_html()))


def test_selects_exactly_the_four_pro_max_256():
    watched = select_watched(discover_products(buypage_html()),
                             "iPhone 18 Pro Max", "256GB", ["*"])
    assert sorted(p.part for p in watched) == sorted(WATCHED)
    assert all(p.price == 1299.00 for p in watched)


def test_selects_named_colors_only():
    watched = select_watched(discover_products(buypage_html()),
                             "iPhone 18 Pro Max", "256GB", ["Black"])
    assert [p.part for p in watched] == ["MJW44LL/A"]


def test_regression_raw_names_would_match_nothing():
    """Pins the bug actually hit: Apple uses U+00A0 in product names, so a
    naive substring match silently yields an empty watch list."""
    raw = json.loads((FIXTURES / "buypage_product_array.json").read_text())
    assert [p for p in raw if "iPhone 18 Pro Max" in p["name"]] == []


def test_empty_selection_raises():
    with pytest.raises(DiscoveryError, match="no products matched"):
        select_watched(discover_products(buypage_html()), "iPhone 42 Pro", "256GB", ["*"])


def test_no_products_at_all_raises():
    with pytest.raises(DiscoveryError, match="no products found"):
        discover_products("<html>nothing here</html>")


# ---------- parsing + canary ----------

def test_parses_canary_as_available_with_stores():
    canary = parse_pickup(pickup_payload(), product_map())[CANARY]
    assert canary.available is True
    assert canary.store_count == 9
    assert "Brickell City Centre" in [s.name for s in canary.stores]


def test_store_details_are_populated():
    results = parse_pickup(pickup_payload(), product_map())
    store = next(s for s in results[CANARY].stores if s.name == "Brickell City Centre")
    assert store.street == "701 S. Miami Avenue"
    assert store.city == "Miami"
    assert store.state == "FL"
    assert store.distance == "0.63 mi"
    assert store.quote == "Available Today"


def test_watched_parts_are_unavailable_in_fixture():
    results = parse_pickup(pickup_payload(), product_map())
    for part in WATCHED:
        assert results[part].available is False
        assert results[part].store_count == 0


def test_canary_healthy_passes():
    check_canary(parse_pickup(pickup_payload(), product_map()), CANARY)


def test_canary_zero_raises_implausible():
    results = parse_pickup(pickup_payload(), product_map())
    results[CANARY] = PartAvailability(CANARY, "iPhone 18 Pro 256GB Black", [])
    with pytest.raises(ImplausibleResponse, match="canary"):
        check_canary(results, CANARY)


def test_missing_canary_raises_implausible():
    results = parse_pickup(pickup_payload(), product_map())
    del results[CANARY]
    with pytest.raises(ImplausibleResponse):
        check_canary(results, CANARY)


def test_all_zero_response_is_rejected_by_canary():
    """The captured all-negative response must never be believed."""
    payload = json.loads((FIXTURES / "availability_session_expired_all_zero.json").read_text())
    results = parse_pickup(payload, product_map())
    with pytest.raises(ImplausibleResponse):
        check_canary(results, CANARY)


def test_malformed_store_entries_are_skipped_not_fatal():
    payload = pickup_payload()
    payload["body"]["stores"].insert(0, {"storeName": "Broken"})
    assert parse_pickup(payload, product_map())[CANARY].store_count == 9


def test_model_prefix_does_not_leak_across_max():
    """'iPhone 18 Pro' must not match 'iPhone 18 Pro Max' -- a bare
    startswith() has no word boundary and silently widens the watch."""
    products = discover_products(buypage_html())
    pro = select_watched(products, "iPhone 18 Pro", "256GB", ["*"])
    names = [p.name for p in pro]
    assert all("Pro Max" not in n for n in names), names
    assert sorted(p.part for p in pro) == ["MJQ34LL/A", "MJQ44LL/A", "MJQ54LL/A", "MJQ64LL/A"]


def test_multiword_colors_still_match():
    products = discover_products(buypage_html())
    watched = select_watched(products, "iPhone 18 Pro Max", "256GB", ["Burgundy"])
    assert [p.part for p in watched] == ["MJW64LL/A"]


def test_stores_are_ordered_nearest_first():
    stores = parse_pickup(pickup_payload(), product_map())[CANARY].stores
    distances = [s.distance_mi for s in stores]
    assert distances == sorted(distances), distances
    assert stores[0].name == "Brickell City Centre"


def test_unparseable_distance_does_not_crash():
    payload = pickup_payload()
    payload["body"]["stores"][0]["storedistance"] = "n/a"
    assert parse_pickup(payload, product_map())[CANARY].store_count == 9

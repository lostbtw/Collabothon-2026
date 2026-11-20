"""Seam: HTTP API."""


def test_companies_lists_both_demo_companies_with_their_as_of_dates(client):
    response = client.get("/api/v1/companies")

    assert response.status_code == 200
    items = {c["id"]: c for c in response.json()["items"]}
    assert items["co_borsuk"]["as_of_date"] == "2026-11-21"
    assert items["co_amalfi"]["as_of_date"] == "2025-05-15"
    assert items["co_amalfi"]["base_currency"] == "EUR"

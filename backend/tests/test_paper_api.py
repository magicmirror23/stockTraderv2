def test_create_and_list_paper_accounts(client):
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 50000, "label": "demo"})
    assert create.status_code == 201
    account_id = create.json()["account_id"]

    listing = client.get("/api/v1/paper/accounts")
    assert listing.status_code == 200
    assert any(account["account_id"] == account_id for account in listing.json())

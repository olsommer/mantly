from automail.support import crm


def test_sync_support_crm_connector_processes_buffer_account_and_nested_contact(monkeypatch):
    cursors: list[dict] = []
    sync_runs: list[dict] = []
    external_runs: list[dict] = []
    external_objects: list[dict] = []

    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "hubspot-main",
            "provider": "hubspot",
            "status": "active",
            "config": {
                "adapter": "buffer",
                "accounts": [
                    {
                        "id": "old-account",
                        "name": "Old Co",
                    },
                    {
                        "id": "acc-1",
                        "name": "Acme",
                        "domain": "acme.example",
                        "url": "https://crm.example/accounts/acc-1",
                        "contacts": [
                            {
                                "id": "person-1",
                                "email": "ana@acme.example",
                                "name": "Ana Acme",
                            }
                        ],
                    },
                ],
            },
        },
    )
    monkeypatch.setattr(
        crm,
        "get_crm_cursor",
        lambda *_args, **_kwargs: {
            "id": "cursor1",
            "cursorValue": "old-account",
            "metadata": {"processedIds": ["account:old-account"]},
        },
    )

    def fake_upsert_account(*, identity, **_kwargs):
        key = identity["account_domain"] or identity["account_name"]
        return {"id": f"account:{key}", "name": identity["account_name"], "domain": identity["account_domain"]}

    def fake_upsert_contact(*, identity, account_id, **_kwargs):
        return {"id": f"contact:{identity['contact_email']}", "accountId": account_id}

    def fake_upsert_external_object(**kwargs):
        rec = {
            "id": f"{kwargs['object_type']}:{kwargs['external_id']}",
            "provider": kwargs["provider"],
            "objectType": kwargs["object_type"],
            "externalId": kwargs["external_id"],
            "accountId": kwargs["account_id"],
            "contactId": kwargs["contact_id"],
        }
        external_objects.append(rec)
        return rec

    monkeypatch.setattr(crm, "upsert_support_account", fake_upsert_account)
    monkeypatch.setattr(crm, "upsert_support_contact", fake_upsert_contact)
    monkeypatch.setattr(crm, "upsert_external_object", fake_upsert_external_object)
    monkeypatch.setattr(
        crm,
        "record_external_sync_run",
        lambda **kwargs: external_runs.append(kwargs) or {"id": "external-sync"},
    )
    monkeypatch.setattr(
        crm,
        "upsert_crm_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(
        crm,
        "record_crm_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "crm-sync1", **kwargs},
    )

    result = crm.sync_support_crm_connector(
        "crm1",
        tenant_id="tenant1",
        project_id="project1",
    )

    assert result["status"] == "success"
    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == 1
    assert result["objectsSeen"] == 2
    assert external_objects == [
        {
            "id": "account:acc-1",
            "provider": "hubspot",
            "objectType": "account",
            "externalId": "acc-1",
            "accountId": "account:acme.example",
            "contactId": "",
        },
        {
            "id": "contact:person-1",
            "provider": "hubspot",
            "objectType": "contact",
            "externalId": "person-1",
            "accountId": "account:acme.example",
            "contactId": "contact:ana@acme.example",
        },
    ]
    assert cursors[0]["status"] == "success"
    assert cursors[0]["cursor_value"] == "acc-1"
    assert cursors[0]["metadata"]["processedIds"] == ["account:acc-1", "account:old-account"]
    assert sync_runs[0]["result"]["objectsSeen"] == 2
    assert len(external_runs) == 2


def test_sync_support_crm_connector_processes_hubspot_companies_and_contacts(monkeypatch):
    calls: list[dict] = []
    cursors: list[dict] = []
    sync_runs: list[dict] = []
    external_runs: list[dict] = []
    external_objects: list[dict] = []

    class FakeResponse:
        def __init__(self, data: dict):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, json: dict, headers: dict):
            calls.append({"url": url, "json": json, "headers": headers})
            if url.endswith("/companies/search"):
                return FakeResponse(
                    {
                        "results": [
                            {
                                "id": "company-1",
                                "updatedAt": "2026-01-01T00:00:00Z",
                                "properties": {
                                    "name": "Acme",
                                    "domain": "acme.example",
                                    "hs_lastmodifieddate": "2026-01-01T00:00:00Z",
                                },
                            }
                        ]
                    }
                )
            return FakeResponse(
                {
                    "results": [
                        {
                            "id": "contact-1",
                            "updatedAt": "2026-01-02T00:00:00Z",
                            "properties": {
                                "email": "ana@acme.example",
                                "firstname": "Ana",
                                "lastname": "Acme",
                                "company": "Acme",
                                "associatedcompanyid": "company-1",
                                "hs_lastmodifieddate": "2026-01-02T00:00:00Z",
                            },
                        }
                    ]
                }
            )

    monkeypatch.setattr(crm.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        crm,
        "load_runtime_secrets",
        lambda tenant_id, project_id: {"HUBSPOT_TOKEN": "pat-secret"},
    )
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "hubspot-main",
            "provider": "hubspot",
            "status": "active",
            "config": {
                "adapter": "hubspot",
                "privateAppTokenEnv": "HUBSPOT_TOKEN",
                "portalId": "12345",
                "apiBaseUrl": "https://api.hubapi.test",
            },
        },
    )
    monkeypatch.setattr(crm, "get_crm_cursor", lambda *_args, **_kwargs: None)

    def fake_upsert_account(*, identity, **_kwargs):
        key = identity["account_domain"] or identity["account_name"]
        return {"id": f"account:{key}", "name": identity["account_name"], "domain": identity["account_domain"]}

    def fake_upsert_contact(*, identity, account_id, **_kwargs):
        return {"id": f"contact:{identity['contact_email']}", "accountId": account_id}

    def fake_upsert_external_object(**kwargs):
        rec = {
            "id": f"{kwargs['object_type']}:{kwargs['external_id']}",
            "provider": kwargs["provider"],
            "objectType": kwargs["object_type"],
            "externalId": kwargs["external_id"],
            "externalUrl": kwargs["external_url"],
            "accountId": kwargs["account_id"],
            "contactId": kwargs["contact_id"],
            "raw": kwargs["raw"],
        }
        external_objects.append(rec)
        return rec

    monkeypatch.setattr(crm, "upsert_support_account", fake_upsert_account)
    monkeypatch.setattr(crm, "upsert_support_contact", fake_upsert_contact)
    monkeypatch.setattr(crm, "upsert_external_object", fake_upsert_external_object)
    monkeypatch.setattr(
        crm,
        "record_external_sync_run",
        lambda **kwargs: external_runs.append(kwargs) or {"id": "external-sync"},
    )
    monkeypatch.setattr(
        crm,
        "upsert_crm_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(
        crm,
        "record_crm_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "crm-sync1", **kwargs},
    )

    result = crm.sync_support_crm_connector("crm1", tenant_id="tenant1", project_id="project1", limit=10)

    assert result["status"] == "success"
    assert result["adapter"] == "hubspot"
    assert result["processed"] == 2
    assert result["failed"] == 0
    assert result["objectsSeen"] == 2
    assert result["cursorValue"] == "1767312000000"
    assert calls[0]["url"] == "https://api.hubapi.test/crm/v3/objects/companies/search"
    assert calls[1]["url"] == "https://api.hubapi.test/crm/v3/objects/contacts/search"
    assert calls[0]["headers"]["Authorization"] == "Bearer pat-secret"
    assert "pat-secret" not in str(result)
    assert external_objects == [
        {
            "id": "account:company-1",
            "provider": "hubspot",
            "objectType": "account",
            "externalId": "company-1",
            "externalUrl": "https://app.hubspot.com/contacts/12345/company/company-1",
            "accountId": "account:acme.example",
            "contactId": "",
            "raw": {
                "objectType": "account",
                "id": "company-1",
                "accountId": "company-1",
                "companyId": "company-1",
                "name": "Acme",
                "accountName": "Acme",
                "domain": "acme.example",
                "website": "",
                "externalUrl": "https://app.hubspot.com/contacts/12345/company/company-1",
                "updatedAt": "2026-01-01T00:00:00Z",
                "cursor": "1767225600000",
                "properties": {
                    "name": "Acme",
                    "domain": "acme.example",
                    "hs_lastmodifieddate": "2026-01-01T00:00:00Z",
                },
            },
        },
        {
            "id": "contact:contact-1",
            "provider": "hubspot",
            "objectType": "contact",
            "externalId": "contact-1",
            "externalUrl": "https://app.hubspot.com/contacts/12345/contact/contact-1",
            "accountId": "account:acme.example",
            "contactId": "contact:ana@acme.example",
            "raw": {
                "objectType": "contact",
                "id": "contact-1",
                "contactId": "contact-1",
                "personId": "contact-1",
                "email": "ana@acme.example",
                "firstName": "Ana",
                "lastName": "Acme",
                "name": "Ana Acme",
                "contactName": "Ana Acme",
                "companyName": "Acme",
                "accountName": "Acme",
                "accountId": "company-1",
                "companyId": "company-1",
                "externalUrl": "https://app.hubspot.com/contacts/12345/contact/contact-1",
                "updatedAt": "2026-01-02T00:00:00Z",
                "cursor": "1767312000000",
                "properties": {
                    "email": "ana@acme.example",
                    "firstname": "Ana",
                    "lastname": "Acme",
                    "company": "Acme",
                    "associatedcompanyid": "company-1",
                    "hs_lastmodifieddate": "2026-01-02T00:00:00Z",
                },
            },
        },
    ]
    assert cursors[0]["status"] == "success"
    assert cursors[0]["metadata"]["processedIds"] == ["account:company-1", "contact:contact-1"]
    assert sync_runs[0]["result"]["processed"] == 2
    assert len(external_runs) == 2


def test_sync_support_crm_connector_hubspot_uses_cursor_filter(monkeypatch):
    calls: list[dict] = []
    cursors: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, json: dict, headers: dict):
            calls.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(crm.httpx, "Client", FakeClient)
    monkeypatch.setattr(crm, "load_runtime_secrets", lambda *_args, **_kwargs: {"HUBSPOT_TOKEN": "pat-secret"})
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "hubspot-main",
            "provider": "hubspot",
            "status": "active",
            "config": {"adapter": "hubspot", "privateAppTokenEnv": "HUBSPOT_TOKEN"},
        },
    )
    monkeypatch.setattr(
        crm,
        "get_crm_cursor",
        lambda *_args, **_kwargs: {
            "id": "cursor1",
            "cursorValue": "2026-01-01T00:00:00Z",
            "metadata": {"processedIds": ["account:company-1"]},
        },
    )
    monkeypatch.setattr(
        crm,
        "upsert_crm_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(crm, "record_crm_sync_run", lambda **kwargs: {"id": "crm-sync1", **kwargs})

    result = crm.sync_support_crm_connector("crm1", tenant_id="tenant1", project_id="project1")

    assert result["status"] == "idle"
    assert len(calls) == 2
    for call in calls:
        assert call["json"]["filterGroups"] == [
            {
                "filters": [
                    {
                        "propertyName": "hs_lastmodifieddate",
                        "operator": "GT",
                        "value": "1767225600000",
                    }
                ]
            }
        ]
    assert cursors[0]["cursor_value"] == "2026-01-01T00:00:00Z"
    assert cursors[0]["metadata"]["processedIds"] == ["account:company-1"]


def test_sync_support_crm_connector_processes_salesforce_accounts_and_contacts(monkeypatch):
    calls: list[dict] = []
    cursors: list[dict] = []
    sync_runs: list[dict] = []
    external_runs: list[dict] = []
    external_objects: list[dict] = []

    class FakeResponse:
        def __init__(self, data: dict):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, params: dict | None = None, headers: dict | None = None):
            calls.append({"url": url, "params": params or {}, "headers": headers or {}})
            query = (params or {}).get("q", "")
            if "FROM Account" in query:
                return FakeResponse(
                    {
                        "done": True,
                        "records": [
                            {
                                "Id": "001",
                                "Name": "Acme",
                                "Website": "https://www.acme.example",
                                "Industry": "Software",
                                "SystemModstamp": "2026-01-01T00:00:00Z",
                                "LastModifiedDate": "2026-01-01T00:00:00Z",
                            }
                        ],
                    }
                )
            return FakeResponse(
                {
                    "done": True,
                    "records": [
                        {
                            "Id": "003",
                            "Email": "ana@acme.example",
                            "FirstName": "Ana",
                            "LastName": "Acme",
                            "Name": "Ana Acme",
                            "AccountId": "001",
                            "Account": {"Id": "001", "Name": "Acme", "Website": "https://acme.example"},
                            "SystemModstamp": "2026-01-02T00:00:00Z",
                            "LastModifiedDate": "2026-01-02T00:00:00Z",
                        }
                    ],
                }
            )

    monkeypatch.setattr(crm.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        crm,
        "load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SALESFORCE_ACCESS_TOKEN": "sf-token",
            "SALESFORCE_INSTANCE_URL": "https://acme.my.salesforce.com",
        },
    )
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "salesforce-main",
            "provider": "salesforce",
            "status": "active",
            "config": {
                "adapter": "salesforce",
                "accessTokenEnv": "SALESFORCE_ACCESS_TOKEN",
                "instanceUrlEnv": "SALESFORCE_INSTANCE_URL",
                "apiVersion": "v61.0",
            },
        },
    )
    monkeypatch.setattr(crm, "get_crm_cursor", lambda *_args, **_kwargs: None)

    def fake_upsert_account(*, identity, **_kwargs):
        key = identity["account_domain"] or identity["account_name"]
        return {"id": f"account:{key}", "name": identity["account_name"], "domain": identity["account_domain"]}

    def fake_upsert_contact(*, identity, account_id, **_kwargs):
        return {"id": f"contact:{identity['contact_email']}", "accountId": account_id}

    def fake_upsert_external_object(**kwargs):
        rec = {
            "id": f"{kwargs['object_type']}:{kwargs['external_id']}",
            "provider": kwargs["provider"],
            "objectType": kwargs["object_type"],
            "externalId": kwargs["external_id"],
            "externalUrl": kwargs["external_url"],
            "accountId": kwargs["account_id"],
            "contactId": kwargs["contact_id"],
            "raw": kwargs["raw"],
        }
        external_objects.append(rec)
        return rec

    monkeypatch.setattr(crm, "upsert_support_account", fake_upsert_account)
    monkeypatch.setattr(crm, "upsert_support_contact", fake_upsert_contact)
    monkeypatch.setattr(crm, "upsert_external_object", fake_upsert_external_object)
    monkeypatch.setattr(
        crm,
        "record_external_sync_run",
        lambda **kwargs: external_runs.append(kwargs) or {"id": "external-sync"},
    )
    monkeypatch.setattr(
        crm,
        "upsert_crm_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(
        crm,
        "record_crm_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "crm-sync1", **kwargs},
    )

    result = crm.sync_support_crm_connector("crm1", tenant_id="tenant1", project_id="project1", limit=10)

    assert result["status"] == "success"
    assert result["adapter"] == "salesforce"
    assert result["processed"] == 2
    assert result["failed"] == 0
    assert result["objectsSeen"] == 2
    assert result["cursorValue"] == "2026-01-02T00:00:00Z"
    assert calls[0]["url"] == "https://acme.my.salesforce.com/services/data/v61.0/query"
    assert calls[0]["headers"]["Authorization"] == "Bearer sf-token"
    assert "FROM Account" in calls[0]["params"]["q"]
    assert "FROM Contact" in calls[1]["params"]["q"]
    assert "sf-token" not in str(result)
    assert external_objects == [
        {
            "id": "account:001",
            "provider": "salesforce",
            "objectType": "account",
            "externalId": "001",
            "externalUrl": "https://acme.my.salesforce.com/lightning/r/Account/001/view",
            "accountId": "account:acme.example",
            "contactId": "",
            "raw": {
                "objectType": "account",
                "id": "001",
                "accountId": "001",
                "customerId": "001",
                "name": "Acme",
                "accountName": "Acme",
                "domain": "acme.example",
                "website": "https://www.acme.example",
                "industry": "Software",
                "externalUrl": "https://acme.my.salesforce.com/lightning/r/Account/001/view",
                "updatedAt": "2026-01-01T00:00:00Z",
                "cursor": "2026-01-01T00:00:00Z",
                "fields": {
                    "Id": "001",
                    "Name": "Acme",
                    "Website": "https://www.acme.example",
                    "Industry": "Software",
                    "SystemModstamp": "2026-01-01T00:00:00Z",
                    "LastModifiedDate": "2026-01-01T00:00:00Z",
                },
            },
        },
        {
            "id": "contact:003",
            "provider": "salesforce",
            "objectType": "contact",
            "externalId": "003",
            "externalUrl": "https://acme.my.salesforce.com/lightning/r/Contact/003/view",
            "accountId": "account:acme.example",
            "contactId": "contact:ana@acme.example",
            "raw": {
                "objectType": "contact",
                "id": "003",
                "contactId": "003",
                "personId": "003",
                "email": "ana@acme.example",
                "firstName": "Ana",
                "lastName": "Acme",
                "name": "Ana Acme",
                "contactName": "Ana Acme",
                "companyName": "Acme",
                "accountName": "Acme",
                "accountId": "001",
                "companyId": "001",
                "domain": "acme.example",
                "website": "https://acme.example",
                "externalUrl": "https://acme.my.salesforce.com/lightning/r/Contact/003/view",
                "updatedAt": "2026-01-02T00:00:00Z",
                "cursor": "2026-01-02T00:00:00Z",
                "fields": {
                    "Id": "003",
                    "Email": "ana@acme.example",
                    "FirstName": "Ana",
                    "LastName": "Acme",
                    "Name": "Ana Acme",
                    "AccountId": "001",
                    "Account": {"Id": "001", "Name": "Acme", "Website": "https://acme.example"},
                    "SystemModstamp": "2026-01-02T00:00:00Z",
                    "LastModifiedDate": "2026-01-02T00:00:00Z",
                },
            },
        },
    ]
    assert cursors[0]["status"] == "success"
    assert cursors[0]["metadata"]["processedIds"] == ["account:001", "contact:003"]
    assert sync_runs[0]["result"]["processed"] == 2
    assert len(external_runs) == 2


def test_sync_support_crm_connector_salesforce_uses_cursor_filter(monkeypatch):
    calls: list[dict] = []
    cursors: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"done": True, "records": []}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, params: dict | None = None, headers: dict | None = None):
            calls.append({"url": url, "params": params or {}, "headers": headers or {}})
            return FakeResponse()

    monkeypatch.setattr(crm.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        crm,
        "load_runtime_secrets",
        lambda *_args, **_kwargs: {
            "SALESFORCE_ACCESS_TOKEN": "sf-token",
            "SALESFORCE_INSTANCE_URL": "https://acme.my.salesforce.com",
        },
    )
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "salesforce-main",
            "provider": "salesforce",
            "status": "active",
            "config": {"adapter": "salesforce"},
        },
    )
    monkeypatch.setattr(
        crm,
        "get_crm_cursor",
        lambda *_args, **_kwargs: {
            "id": "cursor1",
            "cursorValue": "2026-01-01T00:00:00+00:00",
            "metadata": {"processedIds": ["account:001"]},
        },
    )
    monkeypatch.setattr(
        crm,
        "upsert_crm_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(crm, "record_crm_sync_run", lambda **kwargs: {"id": "crm-sync1", **kwargs})

    result = crm.sync_support_crm_connector("crm1", tenant_id="tenant1", project_id="project1")

    assert result["status"] == "idle"
    assert len(calls) == 2
    for call in calls:
        assert "WHERE SystemModstamp > 2026-01-01T00:00:00Z" in call["params"]["q"]
    assert cursors[0]["cursor_value"] == "2026-01-01T00:00:00+00:00"
    assert cursors[0]["metadata"]["processedIds"] == ["account:001"]


def test_sync_support_crm_connector_processes_http_records(monkeypatch):
    calls: list[dict] = []
    cursors: list[dict] = []
    sync_runs: list[dict] = []
    external_runs: list[dict] = []
    external_objects: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [
                    {
                        "objectType": "account",
                        "id": "acc-1",
                        "name": "Acme",
                        "domain": "acme.example",
                        "url": "https://crm.example/accounts/acc-1",
                        "updatedAt": "2026-01-02T00:00:00Z",
                    },
                    {
                        "objectType": "contact",
                        "id": "person-1",
                        "email": "ana@acme.example",
                        "name": "Ana Acme",
                        "accountName": "Acme",
                        "updatedAt": "2026-01-03T00:00:00Z",
                    },
                ],
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, params: dict | None = None, headers: dict | None = None):
            calls.append({"url": url, "params": params or {}, "headers": headers or {}})
            return FakeResponse()

    def fake_upsert_account(*, identity, **_kwargs):
        key = identity["account_domain"] or identity["account_name"]
        return {"id": f"account:{key}", "name": identity["account_name"], "domain": identity["account_domain"]}

    def fake_upsert_contact(*, identity, account_id, **_kwargs):
        return {"id": f"contact:{identity['contact_email']}", "accountId": account_id}

    def fake_upsert_external_object(**kwargs):
        rec = {
            "id": f"{kwargs['object_type']}:{kwargs['external_id']}",
            "provider": kwargs["provider"],
            "objectType": kwargs["object_type"],
            "externalId": kwargs["external_id"],
            "accountId": kwargs["account_id"],
            "contactId": kwargs["contact_id"],
        }
        external_objects.append(rec)
        return rec

    monkeypatch.setattr(crm.httpx, "Client", FakeClient)
    monkeypatch.setattr(crm, "load_runtime_secrets", lambda *_args, **_kwargs: {"CRM_HTTP_TOKEN": "crm-secret"})
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "custom-main",
            "provider": "custom",
            "status": "active",
            "config": {
                "adapter": "http",
                "endpointUrl": "https://crm.example/api/support/accounts",
                "tokenEnv": "CRM_HTTP_TOKEN",
                "recordsPath": "items",
                "cursorPath": "updatedAt",
            },
        },
    )
    monkeypatch.setattr(
        crm,
        "get_crm_cursor",
        lambda *_args, **_kwargs: {
            "id": "cursor1",
            "cursorValue": "2026-01-01T00:00:00Z",
            "metadata": {"processedIds": []},
        },
    )
    monkeypatch.setattr(crm, "upsert_support_account", fake_upsert_account)
    monkeypatch.setattr(crm, "upsert_support_contact", fake_upsert_contact)
    monkeypatch.setattr(crm, "upsert_external_object", fake_upsert_external_object)
    monkeypatch.setattr(
        crm,
        "record_external_sync_run",
        lambda **kwargs: external_runs.append(kwargs) or {"id": "external-sync"},
    )
    monkeypatch.setattr(
        crm,
        "upsert_crm_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(
        crm,
        "record_crm_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "crm-sync1", **kwargs},
    )

    result = crm.sync_support_crm_connector("crm1", tenant_id="tenant1", project_id="project1", limit=10)

    assert result["status"] == "success"
    assert result["adapter"] == "http"
    assert result["processed"] == 2
    assert result["failed"] == 0
    assert result["cursorValue"] == "2026-01-03T00:00:00Z"
    assert calls == [
        {
            "url": "https://crm.example/api/support/accounts",
            "params": {"cursor": "2026-01-01T00:00:00Z", "limit": "10"},
            "headers": {"Authorization": "Bearer crm-secret"},
        }
    ]
    assert external_objects == [
        {
            "id": "account:acc-1",
            "provider": "custom",
            "objectType": "account",
            "externalId": "acc-1",
            "accountId": "account:acme.example",
            "contactId": "",
        },
        {
            "id": "contact:person-1",
            "provider": "custom",
            "objectType": "contact",
            "externalId": "person-1",
            "accountId": "account:acme.example",
            "contactId": "contact:ana@acme.example",
        },
    ]
    assert cursors[0]["status"] == "success"
    assert cursors[0]["metadata"]["processedIds"] == ["account:acc-1", "contact:person-1"]
    assert sync_runs[0]["result"]["processed"] == 2
    assert len(external_runs) == 2
    assert "crm-secret" not in str(result)


def test_sync_support_crm_connector_records_adapter_error(monkeypatch):
    cursors: list[dict] = []
    sync_runs: list[dict] = []
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "zoho-main",
            "provider": "zoho",
            "status": "active",
            "config": {"adapter": "zoho"},
        },
    )
    monkeypatch.setattr(crm, "get_crm_cursor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        crm,
        "upsert_crm_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(
        crm,
        "record_crm_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "crm-sync1", **kwargs},
    )

    result = crm.sync_support_crm_connector("crm1", tenant_id="tenant1", project_id="project1")

    assert result["status"] == "failed"
    assert "not implemented" in result["error"]
    assert cursors[0]["status"] == "failed"
    assert sync_runs[0]["result"]["status"] == "failed"


def test_sync_support_crm_connectors_for_scope_uses_connector_project(monkeypatch):
    calls: list[tuple[str, str | None, str]] = []
    monkeypatch.setattr(
        crm,
        "list_syncable_crm_connectors",
        lambda **_kwargs: [
            {"id": "crm1", "tenantId": "tenant1", "projectId": "project1"},
            {"id": "crm2", "tenantId": "", "projectId": ""},
        ],
    )

    def fake_sync(connector_id: str, **kwargs):
        calls.append((connector_id, kwargs.get("tenant_id"), kwargs["project_id"]))
        return {"processed": 1, "failed": 0, "skipped": 0, "objectsSeen": 2}

    monkeypatch.setattr(crm, "sync_support_crm_connector", fake_sync)

    result = crm.sync_support_crm_connectors_for_scope(limit=5, source="scheduler")

    assert calls == [("crm1", "tenant1", "project1")]
    assert result["connectors"] == 1
    assert result["processed"] == 1
    assert result["objectsSeen"] == 2


def test_ingest_crm_webhook_records_and_processes_event(monkeypatch):
    recorded_events: list[dict] = []
    updated_events: list[dict] = []
    sync_runs: list[dict] = []
    external_runs: list[dict] = []

    monkeypatch.setattr(
        crm,
        "get_crm_connector_by_key",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "tenantId": "tenant1",
            "projectId": "project1",
            "connectorKey": "hubspot-main",
            "provider": "hubspot",
            "config": {},
        },
    )
    monkeypatch.setattr(crm, "get_crm_webhook_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        crm,
        "record_crm_webhook_event",
        lambda **kwargs: recorded_events.append(kwargs) or {"id": "event-row1", **kwargs},
    )
    monkeypatch.setattr(
        crm,
        "update_crm_webhook_event",
        lambda event_id, **kwargs: updated_events.append({"event_id": event_id, **kwargs}) or {"id": event_id, **kwargs},
    )
    monkeypatch.setattr(
        crm,
        "upsert_support_account",
        lambda *, identity, **_kwargs: {"id": f"account:{identity['account_domain']}", "name": identity["account_name"]},
    )
    monkeypatch.setattr(
        crm,
        "upsert_support_contact",
        lambda *, identity, account_id, **_kwargs: {"id": f"contact:{identity['contact_email']}", "accountId": account_id},
    )
    monkeypatch.setattr(
        crm,
        "upsert_external_object",
        lambda **kwargs: {"id": f"{kwargs['object_type']}:{kwargs['external_id']}"},
    )
    monkeypatch.setattr(
        crm,
        "record_external_sync_run",
        lambda **kwargs: external_runs.append(kwargs) or {"id": "external-run1"},
    )
    monkeypatch.setattr(
        crm,
        "record_crm_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "crm-run1"},
    )

    result = crm.ingest_crm_webhook(
        "hubspot-main",
        tenant_id="tenant1",
        project_id="project1",
        payload={
            "events": [
                {
                    "eventId": "evt-1",
                    "eventType": "contact.updated",
                    "objectType": "contact",
                    "data": {
                        "id": "person-1",
                        "email": "ana@acme.example",
                        "name": "Ana Acme",
                        "companyName": "Acme",
                        "domain": "acme.example",
                    },
                }
            ]
        },
    )

    assert result["status"] == "success"
    assert result["processed"] == 1
    assert result["objectsSeen"] == 1
    assert recorded_events[0]["event_id"] == "evt-1"
    assert recorded_events[0]["object_type"] == "contact"
    assert updated_events[0]["status"] == "processed"
    assert sync_runs[0]["source"] == "webhook"
    assert sync_runs[0]["result"]["processed"] == 1
    assert external_runs[0]["provider"] == "hubspot"


def test_ingest_crm_webhook_skips_processed_duplicate(monkeypatch):
    monkeypatch.setattr(
        crm,
        "get_crm_connector_by_key",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "tenantId": "tenant1",
            "projectId": "project1",
            "connectorKey": "hubspot-main",
            "provider": "hubspot",
            "config": {},
        },
    )
    monkeypatch.setattr(
        crm,
        "get_crm_webhook_event",
        lambda *_args, **_kwargs: {"id": "event-row1", "status": "processed"},
    )
    monkeypatch.setattr(crm, "record_crm_sync_run", lambda **kwargs: {"id": "crm-run1", **kwargs})

    result = crm.ingest_crm_webhook(
        "hubspot-main",
        tenant_id="tenant1",
        project_id="project1",
        payload={"eventId": "evt-1", "objectType": "account", "data": {"id": "acc-1", "name": "Acme"}},
    )

    assert result["status"] == "skipped"
    assert result["skipped"] == 1
    assert result["processed"] == 0


def test_validate_crm_connector_hubspot_checks_secret_and_api(monkeypatch):
    calls: list[dict] = []

    class FakeResponse:
        def __init__(self, data: dict):
            self._data = data
            self.status_code = 200
            self.reason_phrase = "OK"
            self.text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, json: dict, headers: dict):
            calls.append({"url": url, "json": json, "headers": headers})
            return FakeResponse({"results": [{"id": "row1"}]})

    monkeypatch.setattr(crm.httpx, "Client", FakeClient)
    monkeypatch.setattr(crm, "load_runtime_secrets", lambda *_args, **_kwargs: {"HUBSPOT_TOKEN": "pat-secret"})
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "hubspot-main",
            "provider": "hubspot",
            "status": "active",
            "config": {"adapter": "hubspot", "privateAppTokenEnv": "HUBSPOT_TOKEN", "apiBaseUrl": "https://api.hubapi.test"},
        },
    )

    result = crm.validate_crm_connector("crm1", tenant_id="tenant1", project_id="project1")

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["adapter"] == "hubspot"
    assert result["envVars"] == [{"name": "HUBSPOT_TOKEN", "required": True, "configured": True, "status": "done"}]
    assert result["sample"] == {"companies": 1, "contacts": 1}
    assert calls[0]["headers"]["Authorization"] == "Bearer pat-secret"
    assert "pat-secret" not in str(result)


def test_validate_crm_connector_salesforce_reports_missing_env(monkeypatch):
    monkeypatch.setattr(crm, "load_runtime_secrets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "salesforce-main",
            "provider": "salesforce",
            "status": "active",
            "config": {
                "adapter": "salesforce",
                "accessTokenEnv": "SF_TOKEN",
                "instanceUrlEnv": "SF_INSTANCE_URL",
            },
        },
    )

    result = crm.validate_crm_connector("crm1", tenant_id="tenant1", project_id="project1")

    assert result["ready"] is False
    assert result["status"] == "missing"
    assert result["envVars"] == [
        {"name": "SF_TOKEN", "required": True, "configured": False, "status": "missing"},
        {"name": "SF_INSTANCE_URL", "required": True, "configured": False, "status": "missing"},
    ]
    assert "SF_TOKEN" in result["error"]
    assert "SF_INSTANCE_URL" in result["error"]


def test_validate_crm_connector_http_checks_endpoint_and_secret(monkeypatch):
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"items": [{"id": "acc-1", "objectType": "account", "name": "Acme"}]}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, params: dict | None = None, headers: dict | None = None):
            calls.append({"url": url, "params": params or {}, "headers": headers or {}})
            return FakeResponse()

    monkeypatch.setattr(crm.httpx, "Client", FakeClient)
    monkeypatch.setattr(crm, "load_runtime_secrets", lambda *_args, **_kwargs: {"CRM_HTTP_TOKEN": "crm-secret"})
    monkeypatch.setattr(
        crm,
        "get_crm_connector",
        lambda *_args, **_kwargs: {
            "id": "crm1",
            "connectorKey": "custom-main",
            "provider": "custom",
            "status": "active",
            "config": {
                "adapter": "http",
                "endpointUrl": "https://crm.example/api/support/accounts",
                "tokenEnv": "CRM_HTTP_TOKEN",
                "recordsPath": "items",
            },
        },
    )

    result = crm.validate_crm_connector("crm1", tenant_id="tenant1", project_id="project1")

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["adapter"] == "http"
    assert result["envVars"] == [{"name": "CRM_HTTP_TOKEN", "required": True, "configured": True, "status": "done"}]
    assert result["sample"] == {"records": 1}
    assert calls == [
        {
            "url": "https://crm.example/api/support/accounts",
            "params": {"limit": "1"},
            "headers": {"Authorization": "Bearer crm-secret"},
        }
    ]
    assert "crm-secret" not in str(result)

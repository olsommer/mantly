from datetime import datetime, timezone

from automail.billing.checkout import create_checkout_session
from automail.billing.plans import (
    get_plan_features,
    get_plan_limits,
    get_tenant_features,
    get_tenant_limits,
    has_feature,
)
from automail.billing.retention import enforce_retention
from automail.billing.subscriptions import _stripe_object_to_dict, get_subscription_details
from automail.billing.tenant import get_effective_tenant_plan
from automail.billing.usage import _current_period_start_iso, check_limit
from automail.billing.webhooks import _handle_subscription_updated, handle_webhook_event


def test_current_period_start_uses_synced_stripe_start(monkeypatch):
    monkeypatch.setattr(
        "automail.billing.usage.get_tenant_record",
        lambda tenant_id: {
            "current_period_start": "2026-05-05T20:43:30+00:00",
            "current_period_end": "2026-06-05T20:43:30+00:00",
        },
    )

    assert _current_period_start_iso("tenant") == "2026-05-05 20:43:30.000Z"


def test_create_checkout_session_uses_requested_business_price(monkeypatch):
    captured = {}

    class CheckoutSessionApi:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return type("Session", (), {"url": "https://checkout.test/session"})()

    class CheckoutApi:
        Session = CheckoutSessionApi

    class StripeApi:
        checkout = CheckoutApi

    monkeypatch.setattr("automail.billing.checkout.STRIPE_BUSINESS_PRICE_ID", "price_business")
    monkeypatch.setattr("automail.billing.checkout._ensure_stripe", lambda: StripeApi)
    monkeypatch.setattr(
        "automail.billing.checkout._get_or_create_stripe_customer_id",
        lambda tenant_id, email: "cus_test",
    )

    url = create_checkout_session(
        "tenant",
        "root@example.com",
        "https://app.test/success",
        "https://app.test/cancel",
        "business",
    )

    assert url == "https://checkout.test/session"
    assert captured["line_items"] == [{"price": "price_business", "quantity": 1}]
    assert captured["metadata"] == {"tenant_id": "tenant", "plan": "business"}
    assert captured["subscription_data"] == {"metadata": {"tenant_id": "tenant", "plan": "business"}}


def test_subscription_updated_uses_item_period_dates(monkeypatch):
    updates = {}

    monkeypatch.setattr("automail.billing.webhooks._find_tenant_by_customer", lambda customer_id: "tenant")
    monkeypatch.setattr("automail.billing.webhooks._patch_tenant", lambda tenant_id, data: updates.update(data))
    monkeypatch.setattr("automail.billing.subscriptions.STRIPE_PRO_PRICE_ID", "price_pro")

    _handle_subscription_updated(
        {
            "id": "sub_test",
            "customer": "cus_test",
            "status": "active",
            "cancel_at_period_end": True,
            "items": {
                "data": [
                    {
                        "price": {"id": "price_pro"},
                        "current_period_start": 1778013810,
                        "current_period_end": 1780692210,
                    }
                ]
            },
        }
    )

    assert updates["subscription_status"] == "active"
    assert updates["plan"] == "pro"
    assert updates["subscription_id"] == "sub_test"
    assert updates["cancel_at_period_end"] is True
    assert updates["current_period_start"] == datetime.fromtimestamp(
        1778013810,
        tz=timezone.utc,
    ).isoformat()
    assert updates["current_period_end"] == datetime.fromtimestamp(
        1780692210,
        tz=timezone.utc,
    ).isoformat()


def test_subscription_updated_hydrates_thin_event(monkeypatch):
    updates = {}

    class SubscriptionApi:
        @staticmethod
        def retrieve(subscription_id):
            assert subscription_id == "sub_test"
            return {
                "id": "sub_test",
                "customer": "cus_test",
                "status": "active",
                "cancel_at_period_end": True,
                "items": {
                    "data": [
                        {
                            "price": {"id": "price_pro"},
                            "current_period_start": 1778013810,
                            "current_period_end": 1780692210,
                        }
                    ]
                },
            }

    class StripeApi:
        Subscription = SubscriptionApi

    monkeypatch.setattr("automail.billing.webhooks._ensure_stripe", lambda: StripeApi)
    monkeypatch.setattr("automail.billing.webhooks._find_tenant_by_customer", lambda customer_id: "tenant")
    monkeypatch.setattr("automail.billing.webhooks._patch_tenant", lambda tenant_id, data: updates.update(data))
    monkeypatch.setattr("automail.billing.subscriptions.STRIPE_PRO_PRICE_ID", "price_pro")

    handle_webhook_event(
        {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_test", "object": "subscription"}},
        }
    )

    assert updates["subscription_id"] == "sub_test"
    assert updates["cancel_at_period_end"] is True
    assert updates["current_period_end"] == datetime.fromtimestamp(
        1780692210,
        tz=timezone.utc,
    ).isoformat()


def test_stripe_object_to_dict_supports_private_recursive_method():
    class StripeObject:
        def _to_dict_recursive(self):
            return {"id": "sub_test", "cancel_at_period_end": True}

    assert _stripe_object_to_dict(StripeObject()) == {
        "id": "sub_test",
        "cancel_at_period_end": True,
    }


def test_subscription_updated_treats_cancel_at_as_scheduled_cancel(monkeypatch):
    updates = {}

    monkeypatch.setattr("automail.billing.webhooks._find_tenant_by_customer", lambda customer_id: "tenant")
    monkeypatch.setattr("automail.billing.webhooks._patch_tenant", lambda tenant_id, data: updates.update(data))
    monkeypatch.setattr("automail.billing.subscriptions.STRIPE_PRO_PRICE_ID", "price_pro")

    _handle_subscription_updated(
        {
            "id": "sub_test",
            "customer": "cus_test",
            "status": "active",
            "cancel_at_period_end": False,
            "cancel_at": 1780692210,
            "items": {
                "data": [
                    {
                        "price": {"id": "price_pro"},
                        "current_period_start": 1778013810,
                        "current_period_end": 1780692210,
                    }
                ]
            },
        }
    )

    assert updates["cancel_at_period_end"] is True
    assert updates["current_period_end"] == datetime.fromtimestamp(
        1780692210,
        tz=timezone.utc,
    ).isoformat()


def test_get_subscription_details_refreshes_cancel_at_period_end(monkeypatch):
    updates = {}

    class SubscriptionApi:
        @staticmethod
        def retrieve(subscription_id):
            assert subscription_id == "sub_test"
            return {
                "id": "sub_test",
                "status": "active",
                "cancel_at_period_end": True,
                "current_period_start": 1778013810,
                "current_period_end": 1780692210,
                "items": {"data": [{"price": {"id": "price_business"}}]},
            }

    class StripeApi:
        Subscription = SubscriptionApi

    monkeypatch.setattr("automail.billing.subscriptions.STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr("automail.billing.subscriptions.STRIPE_BUSINESS_PRICE_ID", "price_business")
    monkeypatch.setattr(
        "automail.billing.subscriptions.get_tenant_record",
        lambda tenant_id: {
            "subscription_id": "sub_test",
            "subscription_status": "active",
            "cancel_at_period_end": False,
        },
    )
    monkeypatch.setattr("automail.billing.subscriptions._ensure_stripe", lambda: StripeApi)
    monkeypatch.setattr("automail.billing.subscriptions._patch_tenant", lambda tenant_id, data: updates.update(data))

    details = get_subscription_details("tenant")

    assert details["status"] == "active"
    assert details["cancel_at_period_end"] is True
    assert updates["plan"] == "business"
    assert details["current_period_end"] == datetime.fromtimestamp(
        1780692210,
        tz=timezone.utc,
    ).isoformat()
    assert updates["cancel_at_period_end"] is True


def test_get_subscription_details_uses_customer_active_subscription(monkeypatch):
    updates = {}

    class SubscriptionApi:
        @staticmethod
        def list(customer, status, limit):
            assert customer == "cus_test"
            assert status == "all"
            assert limit == 10
            return {
                "data": [
                    {
                        "id": "sub_active",
                        "status": "active",
                        "cancel_at_period_end": True,
                        "current_period_start": 1778013810,
                        "current_period_end": 1780692210,
                        "items": {"data": [{"price": {"id": "price_business"}}]},
                    }
                ]
            }

    class StripeApi:
        Subscription = SubscriptionApi

    monkeypatch.setattr("automail.billing.subscriptions.STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr("automail.billing.subscriptions.STRIPE_BUSINESS_PRICE_ID", "price_business")
    monkeypatch.setattr(
        "automail.billing.subscriptions.get_tenant_record",
        lambda tenant_id: {
            "stripe_customer_id": "cus_test",
            "subscription_id": "",
            "subscription_status": "active",
            "cancel_at_period_end": False,
        },
    )
    monkeypatch.setattr("automail.billing.subscriptions._ensure_stripe", lambda: StripeApi)
    monkeypatch.setattr("automail.billing.subscriptions._patch_tenant", lambda tenant_id, data: updates.update(data))

    details = get_subscription_details("tenant")

    assert details["cancel_at_period_end"] is True
    assert updates["plan"] == "business"
    assert updates["subscription_id"] == "sub_active"
    assert updates["cancel_at_period_end"] is True


def test_business_eval_runs_are_unlimited(monkeypatch):
    monkeypatch.setattr("automail.billing.usage.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.usage.get_effective_tenant_plan", lambda tenant_id: "business")
    monkeypatch.setattr(
        "automail.billing.usage.get_usage",
        lambda tenant_id: {
            "emails_this_period": 0,
            "projects": 1,
            "users": 5,
            "eval_runs_this_period": 50_000,
            "eval_sets": 200,
        },
    )

    check_limit("tenant", "eval_runs_per_month")
    check_limit("tenant", "eval_sets")


def test_free_eval_sets_are_limited(monkeypatch):
    monkeypatch.setattr("automail.billing.usage.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.usage.get_effective_tenant_plan", lambda tenant_id: "free")
    monkeypatch.setattr(
        "automail.billing.usage.get_usage",
        lambda tenant_id: {
            "emails_this_period": 0,
            "projects": 1,
            "users": 1,
            "eval_runs_this_period": 0,
            "eval_sets": 1,
        },
    )

    try:
        check_limit("tenant", "eval_sets")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 402
        assert exc.detail["resource"] == "eval_sets"
    else:
        raise AssertionError("Expected eval set limit to be enforced")


def test_plan_feature_matrix_matches_pricing(monkeypatch):
    assert get_plan_features("free")["feedback_learnings"] is False
    assert get_plan_features("pro")["feedback_learnings"] is True
    assert get_plan_features("pro")["security_monitoring"] is False
    assert get_plan_features("business")["security_monitoring"] is True
    assert get_plan_features("business")["byok_llm"] is True


def test_demo_tenant_gets_business_feature_surface(monkeypatch):
    monkeypatch.setattr("automail.billing.plans.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.tenant.get_tenant_plan", lambda tenant_id: "free")
    monkeypatch.setattr("automail.billing.tenant.is_demo_tenant", lambda tenant_id: True)

    assert get_effective_tenant_plan("tenant-demo") == "business"
    assert get_tenant_limits("tenant-demo") == get_plan_limits("business")
    assert get_tenant_features("tenant-demo") == get_plan_features("business")
    assert has_feature("tenant-demo", "security_monitoring") is True


def test_retention_deletes_old_runs_results_chats_and_llm_events(monkeypatch):
    deleted: list[str] = []

    monkeypatch.setattr("automail.billing.retention.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.retention.get_tenant_limit", lambda tenant_id, resource: 30)

    def fake_list_all(collection: str, filter_str: str, *args, **kwargs):
        if collection == "chats":
            return [{"id": "chat_old"}]
        if collection == "eval_runs":
            return [{"id": "run_old"}]
        if collection == "eval_results":
            return [{"id": "result_old"}]
        if collection == "llm_usage_events":
            return [{"id": "usage_old"}]
        return []

    monkeypatch.setattr("automail.db.pocketbase.client._list_all", fake_list_all)
    monkeypatch.setattr("automail.db.pocketbase.client._delete", lambda path: deleted.append(path))

    result = enforce_retention("tenant")

    assert result == {"chats": 1, "eval_runs": 1, "eval_results": 1, "llm_usage_events": 1}
    assert "/api/collections/chats/records/chat_old" in deleted
    assert "/api/collections/eval_results/records/result_old" in deleted
    assert "/api/collections/eval_runs/records/run_old" in deleted
    assert "/api/collections/llm_usage_events/records/usage_old" in deleted

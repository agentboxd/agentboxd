from typing import get_args

from agentboxd import MessageAi, MessageCategory, UrgencyLevel, WebhookEventType


def test_message_ai_enrichment_keys_are_optional() -> None:
    assert MessageAi.__required_keys__ == frozenset({"verification"})
    optional = {"category", "risk", "needs_human", "urgency", "auto_reply", "enriched_at", "enrichment_error"}
    assert optional <= set(MessageAi.__optional_keys__)
    # An unenriched message is still a valid MessageAi.
    plain: MessageAi = {"verification": None}
    assert plain.get("category") is None


def test_enriched_message_ai_shape() -> None:
    ai: MessageAi = {
        "verification": None,
        "category": {
            "label": "billing",
            "confidence": 0.94,
            "probabilities": {"billing": 0.94, "other": 0.06},
        },
        "risk": {"injection": 0.01, "phishing": 0.03},
        "needs_human": 0.22,
        "urgency": {"level": "normal", "score": 1.4, "confidence": 0.7},
        "auto_reply": 0.03,
        "model": "jev",
        "enriched_at": "2026-09-25T12:00:00.000Z",
    }
    assert ai["category"]["label"] == "billing"


def test_literals() -> None:
    assert "message.enriched" in get_args(WebhookEventType)
    assert set(get_args(MessageCategory)) == {
        "support",
        "sales",
        "billing",
        "verification",
        "notification",
        "newsletter",
        "personal",
        "other",
    }
    assert get_args(UrgencyLevel) == ("low", "normal", "high", "critical")

"""Tests for camelCase aliasing + populate_by_name on the DTOs."""

from __future__ import annotations

from shouldibuy.model.dtos import ListingAttributes
from shouldibuy.model.dtos import MarketVerdictDTO
from shouldibuy.model.dtos import Money
from shouldibuy.model.dtos import TypicalRange
from shouldibuy.model.dtos import VerdictDTO
from shouldibuy.model.events import MarketVerdictEvent


def test_market_verdict_emits_camel_case() -> None:
    mv = MarketVerdictDTO(
        state="fair",
        asking=Money(amount=419.99, currency="USD"),
        percentile=50,
        typical_range=TypicalRange(low=379.0, high=430.0, currency="USD"),
        comp_count=11,
    )
    dumped = mv.model_dump(by_alias=True)
    assert dumped["typicalRange"] == {
        "low": 379.0,
        "high": 430.0,
        "currency": "USD",
    }
    assert dumped["compCount"] == 11
    assert "comp_count" not in dumped


def test_populate_by_name_accepts_snake_case() -> None:
    attrs = ListingAttributes(condition_grade="Used")
    assert attrs.condition_grade == "Used"
    assert attrs.model_dump(by_alias=True)["conditionGrade"] == "Used"


def test_verdict_negotiation_message_alias() -> None:
    v = VerdictDTO(
        state="fair",
        headline="Fairly priced.",
        negotiation_message="Offer near $379.",
        confidence="high",
    )
    assert v.model_dump(by_alias=True)["negotiationMessage"] == "Offer near $379."


def test_event_type_discriminator() -> None:
    ev = MarketVerdictEvent(
        market_verdict=MarketVerdictDTO(
            state="fair",
            asking=Money(amount=1.0, currency="USD"),
            comp_count=1,
        )
    )
    dumped = ev.model_dump(by_alias=True)
    assert dumped["type"] == "market_verdict"
    assert "marketVerdict" in dumped

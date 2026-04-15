# ══════════════════════════════════════════════════════════════════════
# ala/arbitrator.py
# ══════════════════════════════════════════════════════════════════════
# LifeCycleArbitrator — two-layer retirement decision engine.
#
# Layer 1 — Hard rules (applied first, override everything):
#   - SoH below operator minimum → route to recycler
#   - RTE below application minimum → route to recycler
#   - SoH above threshold AND price gap within tolerance
#     → waste hierarchy override → second life
#
# Layer 2 — Circular Score (applied if no hard rule fires):
#   - winner = argmax(CircularScore(recycler), CircularScore(sl))
#
# Confidence score:
#   - margin = winner.composite_score - loser.composite_score
#   - HIGH   : margin > 0.20
#   - MEDIUM : margin 0.10–0.20
#   - LOW    : margin < 0.10 → human review flagged
#
# These thresholds are heuristic — thesis phase will calibrate
# them against evaluation dataset outcomes.
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from ala.bids import RecyclerBid, SecondLifeBid
from ala.carbon import DynamicCarbonTracker
from ala.passport import BatteryPassport
from ala.scoring import CircularScore, ScoreResult, ScoringWeights


# ── Decision enumeration ───────────────────────────────────────────────

class ArbiterDecision(Enum):
    SECOND_LIFE_WINS     = "Second-Life wins on Circular Score"
    SECOND_LIFE_OVERRIDE = "Second-Life wins on waste hierarchy override"
    RECYCLER_WINS        = "Recycler awarded contract"
    RECYCLER_DEFAULT     = "Recycler awarded contract — no valid second-life bid"


# ── Confidence levels ──────────────────────────────────────────────────

class ConfidenceLevel(Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"

CONFIDENCE_THRESHOLDS = {
    ConfidenceLevel.HIGH:   0.20,
    ConfidenceLevel.MEDIUM: 0.10,
}


# ── Retirement verdict ─────────────────────────────────────────────────

@dataclass
class RetirementVerdict:
    """
    The complete output of a LifeCycleArbitrator.arbitrate() call.

    Contains the decision, confidence, reasoning chain,
    and all scores for full auditability.
    """

    # ── Core decision ──────────────────────────────────────────────────
    decision:          ArbiterDecision
    winner_name:       str
    winner_bid_type:   str   # 'recycler' or 'second_life'

    # ── Battery state ──────────────────────────────────────────────────
    battery_id:        str
    soh_pct:           float
    remaining_kwh:     float
    lifetime_kg_co2:   float
    carbon_saving_pct: float

    # ── Financials ─────────────────────────────────────────────────────
    recycler_offer:    float
    second_life_offer: Optional[float]

    # ── Scores ─────────────────────────────────────────────────────────
    recycler_score:    ScoreResult
    second_life_score: Optional[ScoreResult]

    # ── Confidence ─────────────────────────────────────────────────────
    confidence:        str
    confidence_margin: float
    human_review:      bool

    # ── Reasoning ─────────────────────────────────────────────────────
    reasoning:         list[str]

    # ── Metadata ──────────────────────────────────────────────────────
    decided_at_utc:    str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def confidence_icon(self) -> str:
        icons = {
            ConfidenceLevel.HIGH.value:   "🟢",
            ConfidenceLevel.MEDIUM.value: "🟡",
            ConfidenceLevel.LOW.value:    "🔴",
        }
        return icons.get(self.confidence, "⚪")

    def print_verdict(self) -> None:
        print("━" * 62)
        print("  RETIREMENT VERDICT")
        print("━" * 62)
        print(f"  Battery        : {self.battery_id}")
        print(f"  SoH            : {self.soh_pct}%")
        print(f"  Remaining kWh  : {self.remaining_kwh} kWh")
        print(f"  Lifetime CO2   : {self.lifetime_kg_co2} kg")
        print(f"  Carbon saving  : {self.carbon_saving_pct}% vs new pack")
        print()
        print(f"  Recycler offer : ${self.recycler_offer:>8.2f}")
        if self.second_life_offer:
            print(f"  2nd-life offer : ${self.second_life_offer:>8.2f}")
        else:
            print(f"  2nd-life offer : WITHDRAWN")
        print()
        print(f"  Decision       : {self.decision.value}")
        print(f"  Winner         : {self.winner_name}")
        print(f"  Confidence     : {self.confidence_icon}  "
              f"{self.confidence}  (margin: {self.confidence_margin:.4f})")
        if self.human_review:
            print(f"  ⚠️  Human review recommended — low confidence decision")
        print()
        print("  Reasoning:")
        for i, step in enumerate(self.reasoning, 1):
            print(f"    {i}. {step}")
        print("━" * 62)

    def to_dict(self) -> dict:
        return {
            "decision":          self.decision.value,
            "winner_name":       self.winner_name,
            "winner_bid_type":   self.winner_bid_type,
            "battery_id":        self.battery_id,
            "soh_pct":           self.soh_pct,
            "remaining_kwh":     self.remaining_kwh,
            "lifetime_kg_co2":   self.lifetime_kg_co2,
            "carbon_saving_pct": self.carbon_saving_pct,
            "recycler_offer":    self.recycler_offer,
            "second_life_offer": self.second_life_offer,
            "recycler_score":    self.recycler_score.to_dict(),
            "second_life_score": (
                self.second_life_score.to_dict()
                if self.second_life_score else None
            ),
            "confidence":        self.confidence,
            "confidence_margin": self.confidence_margin,
            "human_review":      self.human_review,
            "reasoning":         self.reasoning,
            "decided_at_utc":    self.decided_at_utc,
        }


# ── Arbitrator ─────────────────────────────────────────────────────────

class LifeCycleArbitrator:
    """
    Two-layer automated retirement decision engine.

    Takes a BatteryPassport, DynamicCarbonTracker,
    RecyclerBid, and SecondLifeBid and produces a
    RetirementVerdict with full reasoning chain.

    Parameters:
        weights:                  ScoringWeights for CircularScore
        soh_sl_threshold:         SoH above which second-life is viable
        price_override_tolerance: Price gap within which waste hierarchy
                                  override fires (as fraction of sl offer)

    Both threshold values are heuristic in the prototype.
    Thesis phase will calibrate against evaluation dataset.
    """

    def __init__(
        self,
        weights:                  ScoringWeights = None,
        soh_sl_threshold:         float = 75.0,
        price_override_tolerance: float = 0.15,
    ):
        self.scorer                   = CircularScore(weights or ScoringWeights())
        self.soh_sl_threshold         = soh_sl_threshold
        self.price_override_tolerance = price_override_tolerance

    def _compute_confidence(
        self,
        margin: float,
    ) -> tuple[str, bool]:
        """
        Compute confidence level from score margin.

        Returns (confidence_level, human_review_flag).

        Thresholds are heuristic — thesis phase will calibrate
        against evaluation dataset to minimise misclassification.
        """
        if margin > CONFIDENCE_THRESHOLDS[ConfidenceLevel.HIGH]:
            return ConfidenceLevel.HIGH.value, False
        elif margin > CONFIDENCE_THRESHOLDS[ConfidenceLevel.MEDIUM]:
            return ConfidenceLevel.MEDIUM.value, False
        return ConfidenceLevel.LOW.value, True

    def arbitrate(
        self,
        passport:       BatteryPassport,
        tracker:        DynamicCarbonTracker,
        recycler_bid:   RecyclerBid,
        second_life_bid: SecondLifeBid,
        rte_pct:        float = 100.0,
    ) -> RetirementVerdict:
        """
        Run the full two-layer arbitration pipeline.

        Parameters:
            passport:        Battery passport with current state
            tracker:         Carbon tracker with session history
            recycler_bid:    Recycler's bid
            second_life_bid: Second-life operator's bid
            rte_pct:         Round-trip efficiency (default 100 if unknown)

        Returns:
            RetirementVerdict with decision, confidence, and reasoning
        """
        reasoning: list[str] = []

        # ── Extract key values ─────────────────────────────────────────
        s             = passport.strategic
        c             = passport.circularity
        soh_pct       = c.current_soh_pct
        remaining_kwh = passport.remaining_energy_kwh
        energy_kwh    = s.energy_content_kwh

        recycler_offer = recycler_bid.material_value(energy_kwh)
        sl_offer       = second_life_bid.bid_value(
            remaining_kwh, soh_pct, rte_pct
        )
        sl_withdrawal  = second_life_bid.withdrawal_reason(soh_pct, rte_pct)

        # ── Score both bids ────────────────────────────────────────────
        max_financial = max(
            recycler_offer,
            sl_offer if sl_offer else 0.0,
        )

        recycler_score = self.scorer.score_recycler(
            bidder_name         = recycler_bid.bidder_name,
            financial_value_usd = recycler_offer,
            max_financial_value = max_financial,
            soh_pct             = soh_pct,
            carbon_saving_pct   = tracker.carbon_saving_vs_new_pct,
            second_life_exists  = sl_offer is not None,
        )

        if sl_offer is not None:
            sl_score = self.scorer.score_second_life(
                bidder_name         = second_life_bid.bidder_name,
                financial_value_usd = sl_offer,
                max_financial_value = max_financial,
                soh_pct             = soh_pct,
                carbon_saving_pct   = tracker.carbon_saving_vs_new_pct,
            )
        else:
            sl_score = None

        reasoning.append(
            f"Scored both bids — "
            f"Recycler: {recycler_score.composite_score:.4f} | "
            f"Second-Life: "
            f"{f'{sl_score.composite_score:.4f}' if sl_score else 'N/A'}"
        )

        # ══════════════════════════════════════════════════════════════
        # LAYER 1 — Hard rules
        # ══════════════════════════════════════════════════════════════

        # Hard rule 1a — No valid second-life bid
        if sl_offer is None:
            reasoning.append(
                f"Hard rule 1a fired: second-life bid withdrawn — "
                f"{sl_withdrawal}"
            )
            confidence, human_review = self._compute_confidence(
                recycler_score.composite_score
            )
            return RetirementVerdict(
                decision          = ArbiterDecision.RECYCLER_DEFAULT,
                winner_name       = recycler_bid.bidder_name,
                winner_bid_type   = "recycler",
                battery_id        = s.battery_id,
                soh_pct           = soh_pct,
                remaining_kwh     = remaining_kwh,
                lifetime_kg_co2   = tracker.lifetime_kg_co2,
                carbon_saving_pct = tracker.carbon_saving_vs_new_pct,
                recycler_offer    = recycler_offer,
                second_life_offer = None,
                recycler_score    = recycler_score,
                second_life_score = None,
                confidence        = confidence,
                confidence_margin = recycler_score.composite_score,
                human_review      = human_review,
                reasoning         = reasoning,
            )

        # Hard rule 1b — Waste hierarchy override
        # If SoH is above threshold AND price gap is within tolerance,
        # EU waste hierarchy law requires second-life consideration.
        if soh_pct >= self.soh_sl_threshold:
            price_gap_fraction = (
                abs(sl_offer - recycler_offer) / sl_offer
                if sl_offer > 0 else 1.0
            )
            if price_gap_fraction <= self.price_override_tolerance:
                reasoning.append(
                    f"Hard rule 1b fired: waste hierarchy override. "
                    f"SoH {soh_pct}% >= threshold {self.soh_sl_threshold}% "
                    f"and price gap {price_gap_fraction:.1%} "
                    f"<= tolerance {self.price_override_tolerance:.0%}."
                )
                _, _, margin = self.scorer.compare(recycler_score, sl_score)
                confidence, human_review = self._compute_confidence(margin)
                return RetirementVerdict(
                    decision          = ArbiterDecision.SECOND_LIFE_OVERRIDE,
                    winner_name       = second_life_bid.bidder_name,
                    winner_bid_type   = "second_life",
                    battery_id        = s.battery_id,
                    soh_pct           = soh_pct,
                    remaining_kwh     = remaining_kwh,
                    lifetime_kg_co2   = tracker.lifetime_kg_co2,
                    carbon_saving_pct = tracker.carbon_saving_vs_new_pct,
                    recycler_offer    = recycler_offer,
                    second_life_offer = sl_offer,
                    recycler_score    = recycler_score,
                    second_life_score = sl_score,
                    confidence        = confidence,
                    confidence_margin = margin,
                    human_review      = human_review,
                    reasoning         = reasoning,
                )

        # ══════════════════════════════════════════════════════════════
        # LAYER 2 — Circular Score decision
        # ══════════════════════════════════════════════════════════════

        winner_score, loser_score, margin = self.scorer.compare(
            recycler_score, sl_score
        )
        confidence, human_review = self._compute_confidence(margin)

        if winner_score.bid_type == "second_life":
            decision    = ArbiterDecision.SECOND_LIFE_WINS
            winner_name = second_life_bid.bidder_name
            winner_type = "second_life"
            reasoning.append(
                f"No hard rule fired — Layer 2 decision by Circular Score. "
                f"Second-life score {sl_score.composite_score:.4f} "
                f"> recycler score {recycler_score.composite_score:.4f}."
            )
        else:
            decision    = ArbiterDecision.RECYCLER_WINS
            winner_name = recycler_bid.bidder_name
            winner_type = "recycler"
            reasoning.append(
                f"No hard rule fired — Layer 2 decision by Circular Score. "
                f"Recycler score {recycler_score.composite_score:.4f} "
                f"> second-life score {sl_score.composite_score:.4f}."
            )

        return RetirementVerdict(
            decision          = decision,
            winner_name       = winner_name,
            winner_bid_type   = winner_type,
            battery_id        = s.battery_id,
            soh_pct           = soh_pct,
            remaining_kwh     = remaining_kwh,
            lifetime_kg_co2   = tracker.lifetime_kg_co2,
            carbon_saving_pct = tracker.carbon_saving_vs_new_pct,
            recycler_offer    = recycler_offer,
            second_life_offer = sl_offer,
            recycler_score    = recycler_score,
            second_life_score = sl_score,
            confidence        = confidence,
            confidence_margin = margin,
            human_review      = human_review,
            reasoning         = reasoning,
        )
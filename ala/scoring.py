# ══════════════════════════════════════════════════════════════════════
# ala/scoring.py
# ══════════════════════════════════════════════════════════════════════
# CircularScore — composite multi-criteria scoring model.
#
# Scores both recycler and second-life bids across four criteria
# simultaneously to produce a normalised score for each bid.
#
# Current weights are heuristic. Thesis phase will derive
# empirically justified weights through expert elicitation
# using Analytic Hierarchy Process (AHP).
#
# Formula:
#   CircularScore(bid) =
#     w_f * normalize(financial_value)
#     + w_s * normalize(state_of_health)
#     + w_c * normalize(carbon_saving_vs_new_pack)
#     + w_h * hierarchy_compliance_flag
#
#   where w_f=0.35, w_s=0.30, w_c=0.20, w_h=0.15
#   and all weights sum to 1.0
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Scoring weights ────────────────────────────────────────────────────

@dataclass
class ScoringWeights:
    """
    Weights for the four CircularScore criteria.

    Current values are heuristic — not empirically derived.
    Thesis phase will validate these through:
      - Expert elicitation with 3-5 industry practitioners
      - AHP (Analytic Hierarchy Process)
      - Sensitivity analysis on weight variation

    Constraints:
      - All weights must be non-negative
      - Weights must sum to 1.0
    """
    financial:  float = 0.35   # Financial value recovered
    soh:        float = 0.30   # State of health
    carbon:     float = 0.20   # Carbon saving vs new pack
    hierarchy:  float = 0.15   # EU waste hierarchy compliance

    def __post_init__(self):
        if any(w < 0 for w in [
            self.financial, self.soh, self.carbon, self.hierarchy
        ]):
            raise ValueError("All weights must be non-negative")
        total = self.financial + self.soh + self.carbon + self.hierarchy
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.6f}"
            )

    def to_dict(self) -> dict:
        return {
            "financial":  self.financial,
            "soh":        self.soh,
            "carbon":     self.carbon,
            "hierarchy":  self.hierarchy,
        }


# ── Score result ───────────────────────────────────────────────────────

@dataclass
class ScoreResult:
    """
    Detailed score breakdown for a single bid.
    Stores both raw and normalised values for transparency.
    """
    bid_type:            str     # 'recycler' or 'second_life'
    bidder_name:         str

    # Raw input values
    financial_value_usd: float
    soh_pct:             float
    carbon_saving_pct:   float
    hierarchy_compliant: bool

    # Normalised component scores (0.0 to 1.0)
    financial_score:     float
    soh_score:           float
    carbon_score:        float
    hierarchy_score:     float

    # Final weighted composite score
    composite_score:     float

    # Weights used
    weights:             ScoringWeights

    def to_dict(self) -> dict:
        return {
            "bid_type":            self.bid_type,
            "bidder_name":         self.bidder_name,
            "financial_value_usd": self.financial_value_usd,
            "soh_pct":             self.soh_pct,
            "carbon_saving_pct":   self.carbon_saving_pct,
            "hierarchy_compliant": self.hierarchy_compliant,
            "financial_score":     self.financial_score,
            "soh_score":           self.soh_score,
            "carbon_score":        self.carbon_score,
            "hierarchy_score":     self.hierarchy_score,
            "composite_score":     round(self.composite_score, 4),
            "weights":             self.weights.to_dict(),
        }


# ── CircularScore engine ───────────────────────────────────────────────

class CircularScore:
    """
    Composite multi-criteria scoring model for battery retirement.

    Scores both recycler and second-life bids on four criteria:

      1. Financial value (35% weight by default)
         Normalised against the higher of the two bids.

      2. State of Health (30% weight)
         Second-life bid scores on SoH — higher SoH benefits
         second-life more than recycling.
         Recycler scores 1 - (soh/100) since lower SoH means
         more degraded material still has recovery value.

      3. Carbon saving vs new pack (20% weight)
         Second-life scores higher because reuse avoids
         manufacturing a new pack entirely.
         Recycler scores partial credit for material recovery.

      4. EU waste hierarchy compliance (15% weight)
         Binary flag — second-life always scores 1.0,
         recycler scores 0.0 unless no second-life bid exists.

    All component scores are normalised to 0.0–1.0 before weighting.
    Final composite score is also 0.0–1.0.
    """

    # Carbon score reference values
    SECOND_LIFE_CARBON_SCORE = 0.95   # Reuse avoids manufacturing
    RECYCLER_CARBON_SCORE    = 0.40   # Partial credit for recovery

    def __init__(self, weights: ScoringWeights = None):
        self.weights = weights or ScoringWeights()

    def _normalise_financial(
        self,
        value:     float,
        max_value: float,
    ) -> float:
        if max_value <= 0:
            return 0.0
        return min(1.0, value / max_value)

    def _normalise_soh_for_second_life(self, soh_pct: float) -> float:
        """Higher SoH is better for second life."""
        return min(1.0, max(0.0, soh_pct / 100.0))

    def _normalise_soh_for_recycler(self, soh_pct: float) -> float:
        """
        For recycling, material value does not depend on SoH.
        Recycler scores a fixed moderate value on this criterion.
        """
        return 0.50

    def score_recycler(
        self,
        bidder_name:         str,
        financial_value_usd: float,
        max_financial_value: float,
        soh_pct:             float,
        carbon_saving_pct:   float,
        second_life_exists:  bool = True,
    ) -> ScoreResult:
        """
        Compute CircularScore for a recycler bid.

        second_life_exists: if False, hierarchy score is 1.0
        because routing to recycler is the only option.
        """
        f_score = self._normalise_financial(
            financial_value_usd, max_financial_value
        )
        s_score = self._normalise_soh_for_recycler(soh_pct)
        c_score = self.RECYCLER_CARBON_SCORE
        h_score = 0.0 if second_life_exists else 1.0

        composite = (
            self.weights.financial  * f_score
            + self.weights.soh      * s_score
            + self.weights.carbon   * c_score
            + self.weights.hierarchy * h_score
        )

        return ScoreResult(
            bid_type            = "recycler",
            bidder_name         = bidder_name,
            financial_value_usd = financial_value_usd,
            soh_pct             = soh_pct,
            carbon_saving_pct   = carbon_saving_pct,
            hierarchy_compliant = not second_life_exists,
            financial_score     = round(f_score, 4),
            soh_score           = round(s_score, 4),
            carbon_score        = round(c_score, 4),
            hierarchy_score     = round(h_score, 4),
            composite_score     = round(composite, 4),
            weights             = self.weights,
        )

    def score_second_life(
        self,
        bidder_name:         str,
        financial_value_usd: float,
        max_financial_value: float,
        soh_pct:             float,
        carbon_saving_pct:   float,
    ) -> ScoreResult:
        """Compute CircularScore for a second-life bid."""
        f_score = self._normalise_financial(
            financial_value_usd, max_financial_value
        )
        s_score = self._normalise_soh_for_second_life(soh_pct)
        c_score = self.SECOND_LIFE_CARBON_SCORE
        h_score = 1.0   # Second life always hierarchy-compliant

        composite = (
            self.weights.financial  * f_score
            + self.weights.soh      * s_score
            + self.weights.carbon   * c_score
            + self.weights.hierarchy * h_score
        )

        return ScoreResult(
            bid_type            = "second_life",
            bidder_name         = bidder_name,
            financial_value_usd = financial_value_usd,
            soh_pct             = soh_pct,
            carbon_saving_pct   = carbon_saving_pct,
            hierarchy_compliant = True,
            financial_score     = round(f_score, 4),
            soh_score           = round(s_score, 4),
            carbon_score        = round(c_score, 4),
            hierarchy_score     = round(h_score, 4),
            composite_score     = round(composite, 4),
            weights             = self.weights,
        )

    def compare(
        self,
        recycler_score:    ScoreResult,
        second_life_score: ScoreResult,
    ) -> tuple[ScoreResult, ScoreResult, float]:
        """
        Compare two scores and return winner, loser, margin.

        margin = winner.composite_score - loser.composite_score
        """
        if recycler_score.composite_score >= second_life_score.composite_score:
            winner = recycler_score
            loser  = second_life_score
        else:
            winner = second_life_score
            loser  = recycler_score

        margin = round(
            winner.composite_score - loser.composite_score, 4
        )
        return winner, loser, margin

    def print_comparison(
        self,
        recycler_score:    ScoreResult,
        second_life_score: ScoreResult,
    ) -> None:
        winner, loser, margin = self.compare(
            recycler_score, second_life_score
        )
        print("━" * 62)
        print("  CIRCULAR SCORE COMPARISON")
        print("━" * 62)
        print(f"  {'Criterion':<22} {'Weight':>7}"
              f"  {'Recycler':>10}  {'Second Life':>12}")
        print(f"  {'─'*58}")
        print(f"  {'Financial value':<22}"
              f"  {self.weights.financial:>6.0%}"
              f"  {recycler_score.financial_score:>10.4f}"
              f"  {second_life_score.financial_score:>12.4f}")
        print(f"  {'State of Health':<22}"
              f"  {self.weights.soh:>6.0%}"
              f"  {recycler_score.soh_score:>10.4f}"
              f"  {second_life_score.soh_score:>12.4f}")
        print(f"  {'Carbon saving':<22}"
              f"  {self.weights.carbon:>6.0%}"
              f"  {recycler_score.carbon_score:>10.4f}"
              f"  {second_life_score.carbon_score:>12.4f}")
        print(f"  {'Waste hierarchy':<22}"
              f"  {self.weights.hierarchy:>6.0%}"
              f"  {recycler_score.hierarchy_score:>10.4f}"
              f"  {second_life_score.hierarchy_score:>12.4f}")
        print(f"  {'─'*58}")
        print(f"  {'COMPOSITE SCORE':<22}"
              f"  {'':>7}"
              f"  {recycler_score.composite_score:>10.4f}"
              f"  {second_life_score.composite_score:>12.4f}")
        print()
        print(f"  Winner : {winner.bidder_name}")
        print(f"  Margin : {margin:.4f}")
        print("━" * 62)
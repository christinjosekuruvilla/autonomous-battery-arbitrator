# ══════════════════════════════════════════════════════════════════════
# ala/whatif.py
# ══════════════════════════════════════════════════════════════════════
# WhatIfEngine — scenario planning and sensitivity analysis.
#
# Answers the questions operators actually ask:
#   → At what SoH does the second-life bid get withdrawn?
#   → If lithium price doubles, does the recycler win?
#   → Which application gets the best outcome for this battery?
#
# All analysis is read-only — original objects never modified.
#
# Production gaps (thesis future work):
#   - Monte Carlo simulation over price distributions
#   - Fleet-level scenario analysis
#   - Integration with LME price forecasts
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from ala.arbitrator import ArbiterDecision, LifeCycleArbitrator, RetirementVerdict
from ala.bids import RecyclerBid, SecondLifeBid
from ala.carbon import DynamicCarbonTracker
from ala.passport import (
    BatteryPassport,
    BatteryStrategicLayer,
    CircularityLayer,
)
from ala.scoring import ScoringWeights


# ── Scenario result ────────────────────────────────────────────────────

@dataclass
class ScenarioResult:
    """Result of a single what-if scenario run."""
    scenario_name:     str
    parameter_name:    str
    parameter_value:   float
    decision:          str
    winner_name:       str
    confidence:        str
    confidence_margin: float
    recycler_offer:    float
    second_life_offer: Optional[float]

    def to_dict(self) -> dict:
        return {
            "scenario_name":     self.scenario_name,
            "parameter_name":    self.parameter_name,
            "parameter_value":   self.parameter_value,
            "decision":          self.decision,
            "winner_name":       self.winner_name,
            "confidence":        self.confidence,
            "confidence_margin": self.confidence_margin,
            "recycler_offer":    self.recycler_offer,
            "second_life_offer": self.second_life_offer,
        }


# ── WhatIfEngine ───────────────────────────────────────────────────────

class WhatIfEngine:
    """
    Sensitivity analysis on top of a completed arbitration.

    Takes the same passport, tracker, and bids used in the
    main arbitration and runs variations to answer boundary
    questions operators actually ask.

    All analysis is read-only — originals never modified.
    Temporary objects are created for each scenario run.
    """

    def __init__(
        self,
        passport:                 BatteryPassport,
        tracker:                  DynamicCarbonTracker,
        recycler_bid:             RecyclerBid,
        second_life_bid:          SecondLifeBid,
        weights:                  ScoringWeights = None,
        soh_sl_threshold:         float = 75.0,
        price_override_tolerance: float = 0.15,
    ):
        self.passport                 = passport
        self.tracker                  = tracker
        self.recycler_bid             = recycler_bid
        self.second_life_bid          = second_life_bid
        self.arbitrator               = LifeCycleArbitrator(
            weights                  = weights or ScoringWeights(),
            soh_sl_threshold         = soh_sl_threshold,
            price_override_tolerance = price_override_tolerance,
        )

    def _build_passport_with_soh(self, soh_pct: float) -> BatteryPassport:
        """Build a temporary passport with a modified SoH value."""
        s = self.passport.strategic
        c = self.passport.circularity

        temp_strategic = BatteryStrategicLayer(
            battery_id             = s.battery_id,
            manufacturer           = s.manufacturer,
            model_designation      = s.model_designation,
            manufacturing_date     = s.manufacturing_date,
            manufacturing_location = s.manufacturing_location,
            chemistry              = s.chemistry,
            nominal_capacity_ah    = s.nominal_capacity_ah,
            nominal_voltage_v      = s.nominal_voltage_v,
            energy_content_kwh     = s.energy_content_kwh,
            cell_count             = s.cell_count,
            operating_temp_min_c   = s.operating_temp_min_c,
            operating_temp_max_c   = s.operating_temp_max_c,
            soh_eol_threshold_pct          = s.soh_eol_threshold_pct,
            soh_second_life_threshold_pct  = s.soh_second_life_threshold_pct,
            lithium_content_kg     = s.lithium_content_kg,
            cobalt_content_kg      = s.cobalt_content_kg,
            nickel_content_kg      = s.nickel_content_kg,
            manganese_content_kg   = s.manganese_content_kg,
        )
        temp_circularity = CircularityLayer(
            current_soh_pct                  = soh_pct,
            cycle_count                      = c.cycle_count,
            measurement_date                 = c.measurement_date,
            carbon_footprint_kg_co2_per_kwh  = c.carbon_footprint_kg_co2_per_kwh,
            carbon_footprint_scope           = c.carbon_footprint_scope,
            recycled_cobalt_pct              = c.recycled_cobalt_pct,
            recycled_lithium_pct             = c.recycled_lithium_pct,
            recycled_nickel_pct              = c.recycled_nickel_pct,
            recycled_lead_pct                = c.recycled_lead_pct,
            recycled_manganese_pct           = c.recycled_manganese_pct,
            cobalt_supply_chain_verified     = c.cobalt_supply_chain_verified,
            lithium_supply_chain_verified    = c.lithium_supply_chain_verified,
            conflict_minerals_free           = c.conflict_minerals_free,
            lifecycle_state                  = c.lifecycle_state,
            application                      = c.application,
            dismantling_time_minutes         = c.dismantling_time_minutes,
            recyclability_rate_pct           = c.recyclability_rate_pct,
            recovery_efficiency_pct          = c.recovery_efficiency_pct,
        )
        return BatteryPassport(temp_strategic, temp_circularity)

    def _build_recycler_with_li_price(
        self,
        li_price: float,
    ) -> RecyclerBid:
        """Build a temporary recycler bid with a modified lithium price."""
        r = self.recycler_bid
        return RecyclerBid(
            bidder_id               = r.bidder_id,
            bidder_name             = r.bidder_name,
            li_price_per_kg         = li_price,
            co_price_per_kg         = r.co_price_per_kg,
            ni_price_per_kg         = r.ni_price_per_kg,
            mn_price_per_kg         = r.mn_price_per_kg,
            recovery_efficiency_pct = r.recovery_efficiency_pct,
        )

    def _run(
        self,
        passport:     BatteryPassport,
        recycler_bid: RecyclerBid,
    ) -> RetirementVerdict:
        """Run a single arbitration scenario."""
        return self.arbitrator.arbitrate(
            passport        = passport,
            tracker         = self.tracker,
            recycler_bid    = recycler_bid,
            second_life_bid = self.second_life_bid,
        )

    # ── Analysis 1: SoH headroom ───────────────────────────────────────

    def soh_headroom(self) -> dict:
        """
        Show the SoH headroom before the second-life bid is withdrawn.

        The effective breakeven is the operator's minimum SoH —
        below which the bid is formally withdrawn regardless of
        the Circular Score outcome.
        """
        current      = self.passport.circularity.current_soh_pct
        operator_min = self.second_life_bid.min_soh_pct
        headroom     = round(current - operator_min, 2)
        remaining    = self.passport.remaining_energy_kwh

        return {
            "current_soh_pct":    current,
            "operator_min_pct":   operator_min,
            "headroom_pct":       headroom,
            "application":        self.second_life_bid.target_application,
            "price_per_kwh":      self.second_life_bid.price_per_kwh_usd,
            "remaining_kwh":      remaining,
            "interpretation": (
                "VERY HIGH" if headroom > 20
                else "HIGH"   if headroom > 10
                else "MEDIUM" if headroom > 5
                else "LOW"
            ),
        }

    def print_soh_headroom(self) -> None:
        h = self.soh_headroom()
        print("━" * 62)
        print("  WHAT-IF: SoH HEADROOM ANALYSIS")
        print("━" * 62)
        print(f"  Current SoH           : {h['current_soh_pct']}%")
        print(f"  Operator minimum SoH  : {h['operator_min_pct']}%")
        print(f"  Headroom              : {h['headroom_pct']}%"
              f" before bid withdrawn")
        print(f"  Application           : {h['application']}")
        print()

        level = h["interpretation"]
        if level == "VERY HIGH":
            print("  🟢 VERY HIGH headroom — battery has significant"
                  " life remaining")
        elif level == "HIGH":
            print("  🟢 HIGH headroom — battery well within"
                  " second-life range")
        elif level == "MEDIUM":
            print("  🟡 MEDIUM headroom — monitor degradation closely")
        else:
            print("  🔴 LOW headroom — approaching bid withdrawal threshold")

        print()
        print(f"  Note: At ${h['price_per_kwh']}/kWh x"
              f" {h['remaining_kwh']} kWh remaining,")
        print(f"  the price advantage makes the recycler unable to win")
        print(f"  on Circular Score alone. Second life only loses if")
        print(f"  SoH drops below operator minimum"
              f" {h['operator_min_pct']}%.")
        print("━" * 62)

    # ── Analysis 2: Price sensitivity ─────────────────────────────────

    def price_sensitivity(
        self,
        li_multipliers: list[float] = None,
    ) -> list[ScenarioResult]:
        """
        Show how the decision changes as lithium price varies.

        Tests at each multiplier of the current lithium price.
        Returns a list of ScenarioResult for each price point.
        """
        if li_multipliers is None:
            li_multipliers = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]

        base_price = self.recycler_bid.li_price_per_kg
        results    = []
        passport   = self.passport

        for multiplier in li_multipliers:
            new_price    = round(base_price * multiplier, 2)
            temp_recycler = self._build_recycler_with_li_price(new_price)
            verdict       = self._run(passport, temp_recycler)

            results.append(ScenarioResult(
                scenario_name     = "price_sensitivity",
                parameter_name    = "li_price_per_kg",
                parameter_value   = new_price,
                decision          = verdict.decision.value,
                winner_name       = verdict.winner_name,
                confidence        = verdict.confidence,
                confidence_margin = verdict.confidence_margin,
                recycler_offer    = verdict.recycler_offer,
                second_life_offer = verdict.second_life_offer,
            ))

        return results

    def print_price_sensitivity(self) -> None:
        results    = self.price_sensitivity()
        base_price = self.recycler_bid.li_price_per_kg

        print("━" * 62)
        print("  WHAT-IF: LITHIUM PRICE SENSITIVITY")
        print("━" * 62)
        print(f"  Base lithium price: ${base_price}/kg")
        print()
        print(f"  {'Li $/kg':<10} {'Recycler $':<14}"
              f" {'Decision':<32} {'Conf'}")
        print(f"  {'─'*58}")

        base_decision = None
        for r in results:
            flip = ""
            if base_decision is None:
                base_decision = r.decision
            elif r.decision != base_decision:
                flip = "← FLIP"
            decision = r.decision[:30]
            print(f"  ${r.parameter_value:<9.2f}"
                  f" ${r.recycler_offer:<13.2f}"
                  f" {decision:<32}"
                  f" {r.confidence:<8} {flip}")

        print("━" * 62)

    # ── Analysis 3: Application comparison ────────────────────────────

    def application_comparison(self) -> list[dict]:
        """
        Test this battery against all four application presets.

        Shows which applications qualify at the current SoH
        and what bid value each would offer.
        """
        soh     = self.passport.circularity.current_soh_pct
        results = []

        for app_name, preset in SecondLifeBid.APPLICATION_PRESETS.items():
            temp_bid = SecondLifeBid.for_application(
                application       = app_name,
                bidder_id         = "test_operator",
                bidder_name       = f"Test ({app_name})",
                price_per_kwh_usd = self.second_life_bid.price_per_kwh_usd,
            )
            remaining = self.passport.remaining_energy_kwh
            bid_val   = temp_bid.bid_value(remaining, soh)

            results.append({
                "application":  app_name,
                "description":  preset["description"],
                "min_soh_pct":  preset["min_soh_pct"],
                "min_rte_pct":  preset["min_rte_pct"],
                "qualifies":    bid_val is not None,
                "bid_value":    bid_val,
            })

        return results

    def print_application_comparison(self) -> None:
        results = self.application_comparison()
        soh     = self.passport.circularity.current_soh_pct

        print("━" * 62)
        print("  WHAT-IF: APPLICATION COMPARISON")
        print("━" * 62)
        print(f"  Battery SoH: {soh}%")
        print()

        for r in results:
            status = "✅ QUALIFIES" if r["qualifies"] else "❌ WITHDRAWN"
            val    = f"${r['bid_value']:.2f}" if r["bid_value"] else "—"
            print(f"  {status}  {r['application']}")
            print(f"    Min SoH: {r['min_soh_pct']}%  "
                  f"Min RTE: {r['min_rte_pct']}%  "
                  f"Bid value: {val}")
            print(f"    {r['description']}")
            print()

        print("━" * 62)

    def run_all(self) -> None:
        """Run and print all three analyses."""
        print()
        self.print_soh_headroom()
        print()
        self.print_price_sensitivity()
        print()
        self.print_application_comparison()
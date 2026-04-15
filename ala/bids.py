# ══════════════════════════════════════════════════════════════════════
# ala/bids.py
# ══════════════════════════════════════════════════════════════════════
# Bid dataclasses for recyclers and second-life operators.
#
# Production gaps (thesis future work):
#   - Live LME commodity price feed for RecyclerBid
#   - Live IRENA/ESS market price feed for SecondLifeBid
#   - Multi-currency support
#   - Bid expiry and validity windows
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar, Optional


# ── Recycler bid ───────────────────────────────────────────────────────

@dataclass
class RecyclerBid:
    """
    A bid from a battery recycler.

    Values the battery on material content at current spot prices.
    In production, prices would be fetched from the London Metal
    Exchange API rather than passed as arguments.

    Production gaps:
      - No live LME price integration yet (config placeholder exists)
      - No transportation cost modelling
      - No hazardous material handling cost modelling
    """

    # ── Identity ───────────────────────────────────────────────────────
    bidder_id:   str
    bidder_name: str

    # ── Commodity prices (USD/kg) ──────────────────────────────────────
    # Approximate 2024 spot prices — not live LME feed
    li_price_per_kg: float   # Lithium carbonate equivalent
    co_price_per_kg: float   # Cobalt
    ni_price_per_kg: float   # Nickel
    mn_price_per_kg: float   # Manganese

    # ── Process efficiency ─────────────────────────────────────────────
    recovery_efficiency_pct: float = 0.92   # Hydrometallurgical process

    # ── Metadata ───────────────────────────────────────────────────────
    bid_timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""

    def __post_init__(self):
        for name, val in [
            ("li_price_per_kg", self.li_price_per_kg),
            ("co_price_per_kg", self.co_price_per_kg),
            ("ni_price_per_kg", self.ni_price_per_kg),
            ("mn_price_per_kg", self.mn_price_per_kg),
        ]:
            if val < 0:
                raise ValueError(f"{name} cannot be negative")
        if not (0.0 < self.recovery_efficiency_pct <= 1.0):
            raise ValueError(
                "recovery_efficiency_pct must be between 0 and 1"
            )

    def material_value(
        self,
        energy_kwh:       float,
        li_kg_per_kwh:    float = 0.113,
        co_kg_per_kwh:    float = 0.149,
        ni_kg_per_kwh:    float = 0.299,
        mn_kg_per_kwh:    float = 0.104,
    ) -> float:
        """
        Total material recovery value for a battery pack.

        Default material densities are approximate NMC 622 values
        per kWh of pack energy. In production these would be
        read from the passport's material composition fields.

        Formula:
          value = efficiency * sum(material_kg * price_per_kg)
        """
        raw = (
            energy_kwh * li_kg_per_kwh * self.li_price_per_kg
            + energy_kwh * co_kg_per_kwh * self.co_price_per_kg
            + energy_kwh * ni_kg_per_kwh * self.ni_price_per_kg
            + energy_kwh * mn_kg_per_kwh * self.mn_price_per_kg
        )
        return round(raw * self.recovery_efficiency_pct, 2)

    def to_dict(self) -> dict:
        return {
            "type":                    "RecyclerBid",
            "bidder_id":               self.bidder_id,
            "bidder_name":             self.bidder_name,
            "li_price_per_kg":         self.li_price_per_kg,
            "co_price_per_kg":         self.co_price_per_kg,
            "ni_price_per_kg":         self.ni_price_per_kg,
            "mn_price_per_kg":         self.mn_price_per_kg,
            "recovery_efficiency_pct": self.recovery_efficiency_pct,
            "bid_timestamp_utc":       self.bid_timestamp_utc,
            "notes":                   self.notes,
        }


# ── Second life bid ────────────────────────────────────────────────────

@dataclass
class SecondLifeBid:
    """
    A bid from a stationary energy storage operator.

    Values the battery as an energy asset — price per usable kWh.
    Different applications have different technical requirements
    encoded as application presets.

    Production gaps:
      - No live ESS market price feed
      - No transportation and installation cost modelling
      - No operator creditworthiness verification
    """

    # ── Identity ───────────────────────────────────────────────────────
    bidder_id:   str
    bidder_name: str

    # ── Pricing ────────────────────────────────────────────────────────
    price_per_kwh_usd: float   # USD per usable kWh remaining

    # ── Technical requirements ─────────────────────────────────────────
    min_soh_pct:        float          # Minimum SoH accepted
    min_rte_pct:        float = 85.0   # Minimum round-trip efficiency
    max_c_rate:         float = 1.0    # Maximum C-rate requirement
    target_application: str   = "Stationary Energy Storage"

    # ── Metadata ───────────────────────────────────────────────────────
    bid_timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""

    # ── Application presets ────────────────────────────────────────────
    # Minimum requirements by application type.
    # Sources: IRENA Battery Storage Report 2023,
    #          BloombergNEF ESS Market Survey 2024.
    APPLICATION_PRESETS: ClassVar[dict] = {
        "grid_frequency_response": {
            "min_rte_pct": 87.0,
            "min_soh_pct": 78.0,
            "max_c_rate":  2.0,
            "description": "High-frequency grid balancing — highest efficiency required",
        },
        "solar_buffer_storage": {
            "min_rte_pct": 78.0,
            "min_soh_pct": 72.0,
            "max_c_rate":  0.5,
            "description": "Daily solar storage — moderate efficiency acceptable",
        },
        "backup_power": {
            "min_rte_pct": 75.0,
            "min_soh_pct": 70.0,
            "max_c_rate":  0.3,
            "description": "Standby backup — lowest cycling, most tolerant",
        },
        "ev_charging_buffer": {
            "min_rte_pct": 83.0,
            "min_soh_pct": 75.0,
            "max_c_rate":  1.5,
            "description": "EV charging peak shaving — moderate requirements",
        },
    }

    def __post_init__(self):
        if self.price_per_kwh_usd < 0:
            raise ValueError("price_per_kwh_usd cannot be negative")
        if not (0 < self.min_soh_pct <= 100):
            raise ValueError("min_soh_pct must be between 0 and 100")
        if not (0 < self.min_rte_pct <= 100):
            raise ValueError("min_rte_pct must be between 0 and 100")

    @classmethod
    def for_application(
        cls,
        application:       str,
        bidder_id:         str,
        bidder_name:       str,
        price_per_kwh_usd: float,
        notes:             str = "",
    ) -> "SecondLifeBid":
        """
        Convenience constructor using application presets.

        Automatically sets min_rte_pct, min_soh_pct, and max_c_rate
        to the correct values for the application type.
        """
        if application not in cls.APPLICATION_PRESETS:
            valid = list(cls.APPLICATION_PRESETS.keys())
            raise ValueError(
                f"Unknown application '{application}'. "
                f"Valid options: {valid}"
            )
        preset = cls.APPLICATION_PRESETS[application]
        return cls(
            bidder_id          = bidder_id,
            bidder_name        = bidder_name,
            price_per_kwh_usd  = price_per_kwh_usd,
            min_soh_pct        = preset["min_soh_pct"],
            min_rte_pct        = preset["min_rte_pct"],
            max_c_rate         = preset["max_c_rate"],
            target_application = application,
            notes              = notes or preset["description"],
        )

    def bid_value(
        self,
        remaining_kwh: float,
        soh_pct:       float,
        rte_pct:       float = 100.0,
    ) -> Optional[float]:
        """
        Total bid value for a pack with given remaining energy.

        Returns None if the bid is withdrawn due to SoH or RTE
        being below operator minimums.

        Both conditions must pass for the bid to stand:
          1. soh_pct >= min_soh_pct
          2. rte_pct >= min_rte_pct
        """
        if soh_pct < self.min_soh_pct:
            return None
        if rte_pct < self.min_rte_pct:
            return None
        return round(remaining_kwh * self.price_per_kwh_usd, 2)

    def withdrawal_reason(
        self,
        soh_pct: float,
        rte_pct: float = 100.0,
    ) -> Optional[str]:
        """
        Human-readable reason if bid is withdrawn.
        Returns None if the bid stands.
        """
        if soh_pct < self.min_soh_pct:
            return (
                f"SoH {soh_pct}% below operator minimum "
                f"{self.min_soh_pct}% for {self.target_application}"
            )
        if rte_pct < self.min_rte_pct:
            return (
                f"RTE {rte_pct}% below operator minimum "
                f"{self.min_rte_pct}% for {self.target_application}"
            )
        return None

    def print_requirements(self) -> None:
        print(f"  {self.bidder_name} — {self.target_application}")
        print(f"    Price        : ${self.price_per_kwh_usd}/kWh")
        print(f"    Min SoH      : {self.min_soh_pct}%")
        print(f"    Min RTE      : {self.min_rte_pct}%")
        print(f"    Max C-rate   : {self.max_c_rate}C")
        if self.notes:
            print(f"    Notes        : {self.notes}")

    def to_dict(self) -> dict:
        return {
            "type":               "SecondLifeBid",
            "bidder_id":          self.bidder_id,
            "bidder_name":        self.bidder_name,
            "price_per_kwh_usd":  self.price_per_kwh_usd,
            "min_soh_pct":        self.min_soh_pct,
            "min_rte_pct":        self.min_rte_pct,
            "max_c_rate":         self.max_c_rate,
            "target_application": self.target_application,
            "bid_timestamp_utc":  self.bid_timestamp_utc,
            "notes":              self.notes,
        }


# ── Quick test ─────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Recycler bid
    recycler = RecyclerBid(
        bidder_id               = "recycler_001",
        bidder_name             = "EuroRecycle GmbH",
        li_price_per_kg         = 13.00,
        co_price_per_kg         = 28.00,
        ni_price_per_kg         = 14.00,
        mn_price_per_kg         =  2.00,
        recovery_efficiency_pct = 0.92,
        notes                   = "Hydrometallurgical process, ISO 14001 certified",
    )

    # Second life bid using preset
    sl_bid = SecondLifeBid.for_application(
        application       = "solar_buffer_storage",
        bidder_id         = "sl_001",
        bidder_name       = "GridStore Europe BV",
        price_per_kwh_usd = 78.00,
        notes             = "10-year offtake contract",
    )

    # Test against a 75kWh battery at 90% SoH
    energy_kwh    = 75.0
    soh_pct       = 90.0
    remaining_kwh = energy_kwh * soh_pct / 100

    recycler_value = recycler.material_value(energy_kwh)
    sl_value       = sl_bid.bid_value(remaining_kwh, soh_pct)

    print("━" * 58)
    print("  BID SUMMARY")
    print("━" * 58)
    print(f"  Battery    : {energy_kwh} kWh  |  SoH {soh_pct}%"
          f"  |  {remaining_kwh} kWh remaining")
    print()
    print(f"  Recycler   : ${recycler_value:>8.2f}  —  {recycler.bidder_name}")
    if sl_value:
        print(f"  Second life: ${sl_value:>8.2f}  —  {sl_bid.bidder_name}")
        diff = sl_value - recycler_value
        print(f"  Gap        : ${abs(diff):>8.2f}  "
              f"({'Second life' if diff > 0 else 'Recycler'} higher)")
    else:
        reason = sl_bid.withdrawal_reason(soh_pct)
        print(f"  Second life: WITHDRAWN — {reason}")
    print()
    sl_bid.print_requirements()
    print("━" * 58)
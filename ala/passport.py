# ══════════════════════════════════════════════════════════════════════
# ala/passport.py
# ══════════════════════════════════════════════════════════════════════
# Battery passport data model.
#
# Data model is informed by DIN DKE SPEC 99100 v1.3 and
# CEN/CENELEC JTC 24 but this is a proof-of-concept implementation.
# A production implementation would validate incoming data against
# the official DIN DKE SPEC 99100 JSON schema and enforce
# actor-specific access tiers (public, legitimate interest,
# notified body) as defined in EU Battery Regulation 2023/1542.
#
# Known gaps vs production:
#   - No JSON schema validation against official DIN DKE SPEC 99100
#   - No actor-specific access control
#   - No digital signature verification
#   - No QR/URI resolution for passport lookup
#   - Single battery chemistry only (NMC)
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional


# ── Enumerations ───────────────────────────────────────────────────────

class BatteryChemistry(Enum):
    NMC  = "LiNiMnCoO2"
    LFP  = "LiFePO4"
    NCA  = "LiNiCoAlO2"
    LMO  = "LiMn2O4"
    LNMO = "LiNiMnO4"


class LifecycleState(Enum):
    FIRST_LIFE       = "first_life"
    RETIREMENT_EVAL  = "retirement_evaluation"
    SECOND_LIFE      = "second_life"
    END_OF_LIFE      = "end_of_life"
    RECYCLING        = "recycling"


class SoHClassification(Enum):
    EXCELLENT  = "excellent"   # >= 90%
    GOOD       = "good"        # 80–90%
    FAIR       = "fair"        # 70–80%
    POOR       = "poor"        # < 70%


# ── Strategic layer ────────────────────────────────────────────────────

@dataclass
class BatteryStrategicLayer:
    """
    Core battery identity and technical specification.

    Field names and structure are informed by DIN DKE SPEC 99100 v1.3
    strategic data attributes. This is a proof-of-concept data model —
    not a schema-validated passport implementation.

    Fields marked [DIN] correspond to mandatory fields in
    DIN DKE SPEC 99100. Fields marked [EXT] are extensions
    for the arbitration system beyond the standard.
    """

    # ── Identity [DIN] ─────────────────────────────────────────────────
    battery_id:              str            # Unique battery identifier
    manufacturer:            str            # Cell manufacturer name
    model_designation:       str            # Pack model designation
    manufacturing_date:      date           # Date of manufacture
    manufacturing_location:  str            # Country of manufacture
    chemistry:               BatteryChemistry

    # ── Technical specification [DIN] ──────────────────────────────────
    nominal_capacity_ah:     float          # Ah — rated capacity
    nominal_voltage_v:       float          # V — nominal pack voltage
    energy_content_kwh:      float          # kWh — rated energy content
    cell_count:              int            # Total cells in pack
    operating_temp_min_c:    float          # Minimum operating temperature
    operating_temp_max_c:    float          # Maximum operating temperature

    # ── Regulatory thresholds [DIN] ────────────────────────────────────
    soh_eol_threshold_pct:         float = 70.0   # End-of-life SoH threshold
    soh_second_life_threshold_pct: float = 75.0   # Second-life routing threshold

    # ── Material composition [DIN] — weight percentages ────────────────
    lithium_content_kg:   float = 0.0
    cobalt_content_kg:    float = 0.0
    nickel_content_kg:    float = 0.0
    manganese_content_kg: float = 0.0

    def __post_init__(self):
        if self.nominal_capacity_ah <= 0:
            raise ValueError("nominal_capacity_ah must be positive")
        if self.nominal_voltage_v <= 0:
            raise ValueError("nominal_voltage_v must be positive")
        if self.energy_content_kwh <= 0:
            raise ValueError("energy_content_kwh must be positive")
        if self.operating_temp_min_c >= self.operating_temp_max_c:
            raise ValueError("operating_temp_min_c must be less than max")
        if self.soh_eol_threshold_pct >= self.soh_second_life_threshold_pct:
            raise ValueError("EOL threshold must be below second-life threshold")

    def to_dict(self) -> dict:
        return {
            "battery_id":              self.battery_id,
            "manufacturer":            self.manufacturer,
            "model_designation":       self.model_designation,
            "manufacturing_date":      self.manufacturing_date.isoformat(),
            "manufacturing_location":  self.manufacturing_location,
            "chemistry":               self.chemistry.value,
            "nominal_capacity_ah":     self.nominal_capacity_ah,
            "nominal_voltage_v":       self.nominal_voltage_v,
            "energy_content_kwh":      self.energy_content_kwh,
            "cell_count":              self.cell_count,
            "operating_temp_min_c":    self.operating_temp_min_c,
            "operating_temp_max_c":    self.operating_temp_max_c,
            "soh_eol_threshold_pct":   self.soh_eol_threshold_pct,
            "soh_second_life_threshold_pct": self.soh_second_life_threshold_pct,
            "lithium_content_kg":      self.lithium_content_kg,
            "cobalt_content_kg":       self.cobalt_content_kg,
            "nickel_content_kg":       self.nickel_content_kg,
            "manganese_content_kg":    self.manganese_content_kg,
        }

    def sha256(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


# ── Circularity layer ──────────────────────────────────────────────────

@dataclass
class CircularityLayer:
    """
    Circularity and environmental data.

    Informed by JTC24 Digital Product Passport framework and
    EU Battery Regulation 2023/1542 Art. 7 (carbon footprint)
    and Art. 8 (recycled content).
    """

    # ── State of health [DIN] ──────────────────────────────────────────
    current_soh_pct:         float          # Current SoH as percentage
    cycle_count:             int            # Total charge cycles completed
    measurement_date:        date           # Date SoH was measured

    # ── Carbon footprint [EU Battery Reg Art. 7] ───────────────────────
    carbon_footprint_kg_co2_per_kwh: float  # Manufacturing carbon intensity
    carbon_footprint_scope:          str    # Scope 1+2+3 or subset

    # ── Recycled content [EU Battery Reg Art. 8] ───────────────────────
    recycled_cobalt_pct:     float = 0.0
    recycled_lithium_pct:    float = 0.0
    recycled_nickel_pct:     float = 0.0
    recycled_lead_pct:       float = 0.0
    recycled_manganese_pct:  float = 0.0

    # ── Supply chain [DIN] ─────────────────────────────────────────────
    cobalt_supply_chain_verified:  bool = False
    lithium_supply_chain_verified: bool = False
    conflict_minerals_free:        bool = False

    # ── Lifecycle state ────────────────────────────────────────────────
    lifecycle_state:         LifecycleState = LifecycleState.FIRST_LIFE
    application:             str = "Electric Vehicle"

    # ── Dismantling [DIN] ──────────────────────────────────────────────
    dismantling_time_minutes:  int   = 0
    recyclability_rate_pct:    float = 0.0
    recovery_efficiency_pct:   float = 0.0

    def __post_init__(self):
        if not (0.0 <= self.current_soh_pct <= 100.0):
            raise ValueError(
                f"current_soh_pct must be 0–100, got {self.current_soh_pct}"
            )
        for name, val in [
            ("recycled_cobalt_pct",    self.recycled_cobalt_pct),
            ("recycled_lithium_pct",   self.recycled_lithium_pct),
            ("recycled_nickel_pct",    self.recycled_nickel_pct),
            ("recycled_manganese_pct", self.recycled_manganese_pct),
        ]:
            if not (0.0 <= val <= 100.0):
                raise ValueError(f"{name} must be 0–100, got {val}")

    @property
    def soh_classification(self) -> SoHClassification:
        if self.current_soh_pct >= 90.0:
            return SoHClassification.EXCELLENT
        elif self.current_soh_pct >= 80.0:
            return SoHClassification.GOOD
        elif self.current_soh_pct >= 70.0:
            return SoHClassification.FAIR
        return SoHClassification.POOR

    def to_dict(self) -> dict:
        return {
            "current_soh_pct":               self.current_soh_pct,
            "cycle_count":                   self.cycle_count,
            "measurement_date":              self.measurement_date.isoformat(),
            "carbon_footprint_kg_co2_per_kwh": self.carbon_footprint_kg_co2_per_kwh,
            "carbon_footprint_scope":        self.carbon_footprint_scope,
            "recycled_cobalt_pct":           self.recycled_cobalt_pct,
            "recycled_lithium_pct":          self.recycled_lithium_pct,
            "recycled_nickel_pct":           self.recycled_nickel_pct,
            "recycled_lead_pct":             self.recycled_lead_pct,
            "recycled_manganese_pct":        self.recycled_manganese_pct,
            "cobalt_supply_chain_verified":  self.cobalt_supply_chain_verified,
            "lithium_supply_chain_verified": self.lithium_supply_chain_verified,
            "conflict_minerals_free":        self.conflict_minerals_free,
            "lifecycle_state":               self.lifecycle_state.value,
            "application":                   self.application,
            "dismantling_time_minutes":      self.dismantling_time_minutes,
            "recyclability_rate_pct":        self.recyclability_rate_pct,
            "recovery_efficiency_pct":       self.recovery_efficiency_pct,
        }

    def sha256(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


# ── Integrity layer ────────────────────────────────────────────────────

@dataclass
class IntegrityLayer:
    """
    SHA-256 hash chain for tamper detection.

    Note: This is standard SHA-256 used for tamper detection.
    It is not a formally FIPS 180-4 compliant implementation
    in the regulatory sense, and does not replace digital
    signature verification or PKI-based passport authentication
    as would be required in a production EU Battery Passport.
    """
    strategic_sha256:    str
    circularity_sha256:  str
    combined_sha256:     str
    sealed_at_utc:       str

    @classmethod
    def seal(
        cls,
        strategic:   BatteryStrategicLayer,
        circularity: CircularityLayer,
    ) -> "IntegrityLayer":
        s_hash = strategic.sha256()
        c_hash = circularity.sha256()
        combined = hashlib.sha256(
            (s_hash + c_hash).encode()
        ).hexdigest()
        return cls(
            strategic_sha256   = s_hash,
            circularity_sha256 = c_hash,
            combined_sha256    = combined,
            sealed_at_utc      = datetime.now(timezone.utc).isoformat(),
        )

    def verify(
        self,
        strategic:   BatteryStrategicLayer,
        circularity: CircularityLayer,
    ) -> bool:
        s_hash = strategic.sha256()
        c_hash = circularity.sha256()
        combined = hashlib.sha256(
            (s_hash + c_hash).encode()
        ).hexdigest()
        return (
            s_hash   == self.strategic_sha256
            and c_hash   == self.circularity_sha256
            and combined == self.combined_sha256
        )

    def to_dict(self) -> dict:
        return {
            "strategic_sha256":   self.strategic_sha256,
            "circularity_sha256": self.circularity_sha256,
            "combined_sha256":    self.combined_sha256,
            "sealed_at_utc":      self.sealed_at_utc,
        }


# ── Battery passport ───────────────────────────────────────────────────

@dataclass
class BatteryPassport:
    """
    Composite battery passport combining strategic, circularity,
    and integrity layers.

    Proof-of-concept implementation informed by:
      - DIN DKE SPEC 99100 v1.3 (data model structure)
      - CEN/CENELEC JTC 24 (Digital Product Passport framework)
      - EU Battery Regulation 2023/1542 (Art. 7, 8, 65)

    Production gaps (thesis future work):
      - JSON schema validation against official DIN DKE SPEC 99100
      - Actor-specific access tiers
      - Digital signature verification
      - QR/URI passport resolution
    """
    strategic:   BatteryStrategicLayer
    circularity: CircularityLayer
    passport_id: str = field(
        default_factory=lambda: (
            f"EU-BP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
    )
    integrity: Optional[IntegrityLayer] = field(default=None, init=False)

    def __post_init__(self):
        self.integrity = IntegrityLayer.seal(self.strategic, self.circularity)

    @property
    def remaining_energy_kwh(self) -> float:
        """Usable energy at current SoH."""
        return round(
            self.strategic.energy_content_kwh
            * self.circularity.current_soh_pct / 100,
            3,
        )

    @property
    def is_second_life_eligible(self) -> bool:
        return (
            self.circularity.current_soh_pct
            >= self.strategic.soh_second_life_threshold_pct
        )

    def verify_integrity(self) -> bool:
        return self.integrity.verify(self.strategic, self.circularity)

    def eu_compliance_summary(self) -> dict:
        """
        Summary of EU Battery Regulation compliance status.
        Art. 8 recycled content targets (2027 and 2031).
        """
        targets_2027 = {
            "cobalt":    16.0,
            "lithium":    6.0,
            "nickel":     6.0,
        }
        targets_2031 = {
            "cobalt":    26.0,
            "lithium":   12.0,
            "nickel":    15.0,
        }
        c = self.circularity
        actual = {
            "cobalt":  c.recycled_cobalt_pct,
            "lithium": c.recycled_lithium_pct,
            "nickel":  c.recycled_nickel_pct,
        }
        return {
            "passport_id": self.passport_id,
            "2027_targets": {
                m: {
                    "required": targets_2027[m],
                    "actual":   actual[m],
                    "compliant": actual[m] >= targets_2027[m],
                }
                for m in targets_2027
            },
            "2031_targets": {
                m: {
                    "required": targets_2031[m],
                    "actual":   actual[m],
                    "compliant": actual[m] >= targets_2031[m],
                }
                for m in targets_2031
            },
        }

    def to_dict(self) -> dict:
        return {
            "passport_id": self.passport_id,
            "strategic":   self.strategic.to_dict(),
            "circularity": self.circularity.to_dict(),
            "integrity":   self.integrity.to_dict(),
        }

    def print_summary(self) -> None:
        s = self.strategic
        c = self.circularity
        print("━" * 60)
        print("  BATTERY PASSPORT SUMMARY")
        print("━" * 60)
        print(f"  Passport ID  : {self.passport_id}")
        print(f"  Battery ID   : {s.battery_id}")
        print(f"  Model        : {s.model_designation}")
        print(f"  Chemistry    : {s.chemistry.value}")
        print(f"  Capacity     : {s.energy_content_kwh} kWh nominal")
        print(f"  SoH          : {c.current_soh_pct}%"
              f"  [{c.soh_classification.value}]")
        print(f"  Remaining    : {self.remaining_energy_kwh} kWh usable")
        print(f"  Cycles       : {c.cycle_count}")
        print(f"  Lifecycle    : {c.lifecycle_state.value}")
        print(f"  2nd life ok  : {'✅ YES' if self.is_second_life_eligible else '❌ NO'}")
        print(f"  Integrity    : {'✅ VERIFIED' if self.verify_integrity() else '❌ BROKEN'}")
        print("━" * 60)
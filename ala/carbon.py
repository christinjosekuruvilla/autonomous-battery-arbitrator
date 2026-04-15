# ══════════════════════════════════════════════════════════════════════
# ala/carbon.py
# ══════════════════════════════════════════════════════════════════════
# Dynamic carbon tracking across a battery's operational lifetime.
#
# Tracks per-session CO2 accumulation using real grid carbon
# intensity data from the Electricity Maps API.
#
# Production gaps (thesis future work):
#   - Historical session data from real BMS records
#   - Automatic region detection from GPS coordinates
#   - Offline fallback dataset for API unavailability
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import requests

# ── Grid region registry ───────────────────────────────────────────────

@dataclass
class GridRegion:
    """A single electricity grid region with carbon intensity data."""
    code:              str    # ISO country/zone code
    name:              str    # Human-readable name
    intensity_g_co2:   float  # gCO2/kWh — fallback if API unavailable
    energy_mix:        str    # Dominant generation mix description

GRID: dict[str, GridRegion] = {
    "NO": GridRegion("NO", "Norway",         26.0,  "Hydro dominant"),
    "FR": GridRegion("FR", "France",         67.0,  "Nuclear dominant"),
    "DE": GridRegion("DE", "Germany",        380.0, "Gas/coal mix"),
    "NL": GridRegion("NL", "Netherlands",    298.0, "Gas dominant"),
    "PL": GridRegion("PL", "Poland",         720.0, "Coal dominant"),
    "ES": GridRegion("ES", "Spain",          165.0, "Mixed renewable"),
    "IT": GridRegion("IT", "Italy",          233.0, "Gas dominant"),
    "SE": GridRegion("SE", "Sweden",          45.0, "Hydro/nuclear"),
    "AT": GridRegion("AT", "Austria",         94.0, "Hydro dominant"),
    "CH": GridRegion("CH", "Switzerland",     28.0, "Hydro/nuclear"),
}


# ── Live grid API ──────────────────────────────────────────────────────

def fetch_live_intensity(
    region_code: str,
    api_key:     str,
) -> Optional[float]:
    """
    Fetch live carbon intensity from Electricity Maps API.

    Returns gCO2/kWh or None if the request fails.
    Failure is handled gracefully — falls back to hardcoded values.
    """
    url = f"https://api.electricitymap.org/v3/carbon-intensity/latest"
    try:
        response = requests.get(
            url,
            headers={"auth-token": api_key},
            params={"zone": region_code},
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json()
            return float(data.get("carbonIntensity", 0))
    except Exception:
        pass
    return None


def get_grid_intensity(
    region_code:    str,
    api_key:        str  = "",
    use_live:       bool = True,
) -> tuple[float, str]:
    """
    Get carbon intensity for a region.

    Returns (intensity_g_co2, source) where source is
    'live' or 'fallback'.

    Priority:
      1. Live Electricity Maps API (if use_live and api_key provided)
      2. Hardcoded fallback values in GRID registry
      3. European average (300 g/kWh) if region not in registry
    """
    if use_live and api_key:
        live = fetch_live_intensity(region_code, api_key)
        if live is not None:
            return live, "live"

    if region_code in GRID:
        return GRID[region_code].intensity_g_co2, "fallback"

    return 300.0, "default"


# ── Charging session ───────────────────────────────────────────────────

@dataclass
class ChargingSession:
    """
    A single charging event with location and energy data.

    In production this would be ingested from BMS telemetry
    via a vehicle API such as Smartcar or OEM fleet endpoints.
    Currently populated from simulated session records.
    """
    session_id:       str
    region_code:      str
    energy_kwh:       float          # kWh charged in this session
    grid_intensity:   float          # gCO2/kWh at time of charging
    data_source:      str = "simulated"   # 'live', 'fallback', 'simulated'
    notes:            str = ""

    @property
    def carbon_kg(self) -> float:
        """CO2 emitted for this session in kg."""
        return round(self.energy_kwh * self.grid_intensity / 1000, 4)

    def to_dict(self) -> dict:
        return {
            "session_id":     self.session_id,
            "region_code":    self.region_code,
            "energy_kwh":     self.energy_kwh,
            "grid_intensity": self.grid_intensity,
            "carbon_kg":      self.carbon_kg,
            "data_source":    self.data_source,
            "notes":          self.notes,
        }


# ── Carbon tracker ─────────────────────────────────────────────────────

class DynamicCarbonTracker:
    """
    Accumulates operational carbon across a battery's lifetime.

    Per-session CO2 accumulation linked to individual battery
    passport records. Integrates live grid intensity data from
    Electricity Maps API when available.

    This is a proof-of-concept implementation. Production would:
      - Ingest sessions from real BMS telemetry
      - Resolve GPS coordinates to grid zones automatically
      - Store session history in a database with audit trail
    """

    # Manufacturing carbon reference for a new 75kWh NMC pack
    # Source: Lifecycle assessment literature (approximate)
    MANUFACTURING_CARBON_KG_PER_KWH = 85.0

    def __init__(
        self,
        battery_id:      str,
        energy_kwh:      float,
        api_key:         str  = "",
        use_live:        bool = True,
    ):
        self.battery_id  = battery_id
        self.energy_kwh  = energy_kwh
        self.api_key     = api_key
        self.use_live    = use_live
        self.sessions:   list[ChargingSession] = []

    def add_session(
        self,
        session_id:    str,
        region_code:   str,
        energy_kwh:    float,
        notes:         str = "",
    ) -> ChargingSession:
        """
        Add a charging session and compute its carbon footprint.
        Fetches live grid intensity if API key is configured.
        """
        intensity, source = get_grid_intensity(
            region_code = region_code,
            api_key     = self.api_key,
            use_live    = self.use_live,
        )
        session = ChargingSession(
            session_id     = session_id,
            region_code    = region_code,
            energy_kwh     = energy_kwh,
            grid_intensity = intensity,
            data_source    = source,
            notes          = notes,
        )
        self.sessions.append(session)
        return session

    def add_sessions_bulk(
        self,
        records: list[dict],
    ) -> list[ChargingSession]:
        """
        Add multiple sessions at once.

        Each record must have: session_id, region_code, energy_kwh
        Optional: notes
        """
        return [
            self.add_session(
                session_id  = r["session_id"],
                region_code = r["region_code"],
                energy_kwh  = r["energy_kwh"],
                notes       = r.get("notes", ""),
            )
            for r in records
        ]

    @property
    def total_energy_kwh(self) -> float:
        return round(sum(s.energy_kwh for s in self.sessions), 3)

    @property
    def lifetime_kg_co2(self) -> float:
        return round(sum(s.carbon_kg for s in self.sessions), 3)

    @property
    def manufacturing_kg_co2(self) -> float:
        return round(
            self.energy_kwh * self.MANUFACTURING_CARBON_KG_PER_KWH,
            3,
        )

    @property
    def carbon_saving_vs_new_pct(self) -> float:
        """
        Carbon saving from reuse vs manufacturing a new pack.
        Higher is better — avoids manufacturing emissions.
        """
        if self.manufacturing_kg_co2 == 0:
            return 0.0
        saving = (
            (self.manufacturing_kg_co2 - self.lifetime_kg_co2)
            / self.manufacturing_kg_co2
            * 100
        )
        return round(max(0.0, saving), 2)

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def region_breakdown(self) -> dict[str, dict]:
        """Carbon breakdown by charging region."""
        breakdown: dict[str, dict] = {}
        for s in self.sessions:
            if s.region_code not in breakdown:
                breakdown[s.region_code] = {
                    "sessions":   0,
                    "energy_kwh": 0.0,
                    "carbon_kg":  0.0,
                }
            breakdown[s.region_code]["sessions"]   += 1
            breakdown[s.region_code]["energy_kwh"] += s.energy_kwh
            breakdown[s.region_code]["carbon_kg"]  += s.carbon_kg
        return breakdown

    def print_summary(self) -> None:
        print("━" * 60)
        print("  CARBON TRACKER SUMMARY")
        print("━" * 60)
        print(f"  Battery ID       : {self.battery_id}")
        print(f"  Sessions         : {self.session_count}")
        print(f"  Total energy     : {self.total_energy_kwh} kWh")
        print(f"  Lifetime CO2     : {self.lifetime_kg_co2} kg")
        print(f"  Manufacturing CO2: {self.manufacturing_kg_co2} kg")
        print(f"  Carbon saving    : {self.carbon_saving_vs_new_pct}%"
              f" vs new pack")
        print()
        print("  By region:")
        for code, data in self.region_breakdown().items():
            name = GRID[code].name if code in GRID else code
            print(f"    {name:<14}"
                  f"  {data['sessions']:>3} sessions"
                  f"  {data['energy_kwh']:>7.1f} kWh"
                  f"  {data['carbon_kg']:>7.3f} kg CO2")
        print("━" * 60)

    def to_dict(self) -> dict:
        return {
            "battery_id":            self.battery_id,
            "session_count":         self.session_count,
            "total_energy_kwh":      self.total_energy_kwh,
            "lifetime_kg_co2":       self.lifetime_kg_co2,
            "manufacturing_kg_co2":  self.manufacturing_kg_co2,
            "carbon_saving_vs_new_pct": self.carbon_saving_vs_new_pct,
            "sessions":              [s.to_dict() for s in self.sessions],
        }


# ── Quick test ─────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Load API key if available
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config"
        ))
        from config import ELECTRICITY_MAPS_API_KEY
    except ImportError:
        ELECTRICITY_MAPS_API_KEY = ""

    tracker = DynamicCarbonTracker(
        battery_id  = "BAT-001",
        energy_kwh  = 75.0,
        api_key     = ELECTRICITY_MAPS_API_KEY,
        use_live    = bool(ELECTRICITY_MAPS_API_KEY),
    )

    sessions = [
        {"session_id": "S001", "region_code": "DE", "energy_kwh": 65.2},
        {"session_id": "S002", "region_code": "NO", "energy_kwh": 71.1},
        {"session_id": "S003", "region_code": "FR", "energy_kwh": 68.4},
        {"session_id": "S004", "region_code": "PL", "energy_kwh": 63.8},
        {"session_id": "S005", "region_code": "DE", "energy_kwh": 70.0},
    ]

    tracker.add_sessions_bulk(sessions)
    tracker.print_summary()
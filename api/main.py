# ══════════════════════════════════════════════════════════════════════
# api/main.py
# ══════════════════════════════════════════════════════════════════════
# FastAPI endpoint for the Autonomous Life-Cycle Arbitrator.
#
# Exposes the arbitration pipeline as a REST API so any platform
# can call it with battery data and receive a verdict JSON.
#
# Production gaps (thesis future work):
#   - Authentication and API key management
#   - Rate limiting
#   - Database persistence for audit log
#   - Async BMS data ingestion
#   - EU Battery Passport registry integration
#
# Run locally:
#   uvicorn api.main:app --reload
#
# Then open: http://localhost:8000/docs
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ala.arbitrator import LifeCycleArbitrator
from ala.bids import RecyclerBid, SecondLifeBid
from ala.carbon import DynamicCarbonTracker
from ala.certificates import CertificateFactory
from ala.passport import (
    BatteryChemistry,
    BatteryPassport,
    BatteryStrategicLayer,
    CircularityLayer,
    LifecycleState,
)
from ala.report import ArbitrationReport
from ala.scoring import ScoringWeights
from ala.validation import DataValidationAgent


# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Autonomous Life-Cycle Arbitrator",
    description = (
        "Automated retirement decision engine for EV batteries. "
        "Implements EU Battery Regulation 2023/1542 waste hierarchy "
        "enforcement with multi-criteria circular scoring. "
        "Proof-of-concept — see /docs for full API reference."
    ),
    version     = "2.0.0",
)


# ── Request models ─────────────────────────────────────────────────────

class BatteryInput(BaseModel):
    """Core battery data required for arbitration."""

    # Identity
    battery_id:              str   = Field(..., example="BAT-001")
    manufacturer:            str   = Field(..., example="CATL")
    model_designation:       str   = Field(..., example="EV-NMC-75kWh-Gen2")
    manufacturing_date:      str   = Field(..., example="2021-06-15")
    manufacturing_location:  str   = Field(..., example="DE")
    chemistry:               str   = Field(..., example="NMC")

    # Technical
    nominal_capacity_ah:     float = Field(..., example=200.0)
    nominal_voltage_v:       float = Field(..., example=375.0)
    energy_content_kwh:      float = Field(..., example=75.0)
    cell_count:              int   = Field(..., example=96)
    operating_temp_min_c:    float = Field(..., example=-20.0)
    operating_temp_max_c:    float = Field(..., example=60.0)

    # State
    current_soh_pct:         float = Field(..., example=90.0)
    cycle_count:             int   = Field(..., example=487)

    # Carbon
    carbon_footprint_kg_co2_per_kwh: float = Field(..., example=85.0)

    # Material content (kg)
    lithium_content_kg:   float = Field(default=8.5,  example=8.5)
    cobalt_content_kg:    float = Field(default=11.2, example=11.2)
    nickel_content_kg:    float = Field(default=22.4, example=22.4)
    manganese_content_kg: float = Field(default=7.8,  example=7.8)

    # Recycled content (%)
    recycled_cobalt_pct:  float = Field(default=0.0, example=12.0)
    recycled_lithium_pct: float = Field(default=0.0, example=4.0)
    recycled_nickel_pct:  float = Field(default=0.0, example=4.0)

    # Safety data for certificate
    max_temp_c:            float = Field(default=45.0, example=42.0)
    min_cell_voltage_v:    float = Field(default=3.5,  example=3.6)
    insulation_ok:         bool  = Field(default=True, example=True)
    rte_pct:               float = Field(default=100.0, example=91.0)


class ChargingSessionInput(BaseModel):
    """A single charging session record."""
    session_id:   str   = Field(..., example="S001")
    region_code:  str   = Field(..., example="DE")
    energy_kwh:   float = Field(..., example=65.2)
    notes:        str   = Field(default="")


class RecyclerBidInput(BaseModel):
    """Recycler bid parameters."""
    bidder_id:               str   = Field(..., example="recycler_001")
    bidder_name:             str   = Field(..., example="EuroRecycle GmbH")
    li_price_per_kg:         float = Field(..., example=13.0)
    co_price_per_kg:         float = Field(..., example=28.0)
    ni_price_per_kg:         float = Field(..., example=14.0)
    mn_price_per_kg:         float = Field(..., example=2.0)
    recovery_efficiency_pct: float = Field(default=0.92, example=0.92)
    notes:                   str   = Field(default="")


class SecondLifeBidInput(BaseModel):
    """
    Second-life bid — either use a preset application or
    specify requirements manually.
    """
    bidder_id:         str   = Field(..., example="sl_001")
    bidder_name:       str   = Field(..., example="GridStore Europe BV")
    price_per_kwh_usd: float = Field(..., example=78.0)

    # Option A — use application preset
    application: Optional[str] = Field(
        default=None,
        example="solar_buffer_storage",
        description=(
            "One of: grid_frequency_response, solar_buffer_storage, "
            "backup_power, ev_charging_buffer"
        ),
    )

    # Option B — specify manually
    min_soh_pct: Optional[float] = Field(default=None, example=75.0)
    min_rte_pct: Optional[float] = Field(default=None, example=85.0)
    max_c_rate:  Optional[float] = Field(default=None, example=1.0)
    notes:       str             = Field(default="")


class ArbitrateRequest(BaseModel):
    """Full arbitration request."""
    battery:          BatteryInput
    sessions:         list[ChargingSessionInput]
    recycler_bid:     RecyclerBidInput
    second_life_bid:  SecondLifeBidInput
    use_live_carbon:  bool = Field(
        default=False,
        description="Fetch live grid carbon intensity from Electricity Maps API",
    )


# ── Helper functions ───────────────────────────────────────────────────

CHEMISTRY_MAP = {
    "NMC":  BatteryChemistry.NMC,
    "LFP":  BatteryChemistry.LFP,
    "NCA":  BatteryChemistry.NCA,
    "LMO":  BatteryChemistry.LMO,
    "LNMO": BatteryChemistry.LNMO,
}


def build_passport(b: BatteryInput) -> BatteryPassport:
    chemistry = CHEMISTRY_MAP.get(b.chemistry.upper())
    if chemistry is None:
        raise HTTPException(
            status_code = 422,
            detail      = f"Unknown chemistry '{b.chemistry}'. "
                          f"Valid options: {list(CHEMISTRY_MAP.keys())}",
        )
    try:
        mfg_date = date.fromisoformat(b.manufacturing_date)
    except ValueError:
        raise HTTPException(
            status_code = 422,
            detail      = f"Invalid manufacturing_date '{b.manufacturing_date}'. "
                          f"Use YYYY-MM-DD format.",
        )

    strategic = BatteryStrategicLayer(
        battery_id             = b.battery_id,
        manufacturer           = b.manufacturer,
        model_designation      = b.model_designation,
        manufacturing_date     = mfg_date,
        manufacturing_location = b.manufacturing_location,
        chemistry              = chemistry,
        nominal_capacity_ah    = b.nominal_capacity_ah,
        nominal_voltage_v      = b.nominal_voltage_v,
        energy_content_kwh     = b.energy_content_kwh,
        cell_count             = b.cell_count,
        operating_temp_min_c   = b.operating_temp_min_c,
        operating_temp_max_c   = b.operating_temp_max_c,
        lithium_content_kg     = b.lithium_content_kg,
        cobalt_content_kg      = b.cobalt_content_kg,
        nickel_content_kg      = b.nickel_content_kg,
        manganese_content_kg   = b.manganese_content_kg,
    )
    circularity = CircularityLayer(
        current_soh_pct                 = b.current_soh_pct,
        cycle_count                     = b.cycle_count,
        measurement_date                = date.today(),
        carbon_footprint_kg_co2_per_kwh = b.carbon_footprint_kg_co2_per_kwh,
        carbon_footprint_scope          = "Scope 1+2+3",
        recycled_cobalt_pct             = b.recycled_cobalt_pct,
        recycled_lithium_pct            = b.recycled_lithium_pct,
        recycled_nickel_pct             = b.recycled_nickel_pct,
        lifecycle_state                 = LifecycleState.RETIREMENT_EVAL,
    )
    return BatteryPassport(strategic, circularity)


def build_sl_bid(s: SecondLifeBidInput) -> SecondLifeBid:
    if s.application:
        return SecondLifeBid.for_application(
            application       = s.application,
            bidder_id         = s.bidder_id,
            bidder_name       = s.bidder_name,
            price_per_kwh_usd = s.price_per_kwh_usd,
            notes             = s.notes,
        )
    if s.min_soh_pct is None:
        raise HTTPException(
            status_code = 422,
            detail      = "Provide either 'application' preset or 'min_soh_pct'",
        )
    return SecondLifeBid(
        bidder_id          = s.bidder_id,
        bidder_name        = s.bidder_name,
        price_per_kwh_usd  = s.price_per_kwh_usd,
        min_soh_pct        = s.min_soh_pct,
        min_rte_pct        = s.min_rte_pct or 85.0,
        max_c_rate         = s.max_c_rate  or 1.0,
        notes              = s.notes,
    )


# ── Routes ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "name":        "Autonomous Life-Cycle Arbitrator",
        "version":     "2.0.0",
        "status":      "running",
        "description": (
            "Automated EV battery retirement decision engine. "
            "POST to /arbitrate with battery data to get a verdict."
        ),
        "docs":        "/docs",
        "regulation":  "EU Battery Regulation 2023/1542",
        "disclaimer":  (
            "Proof-of-concept implementation. "
            "Data model informed by DIN DKE SPEC 99100 v1.3. "
            "Not a formally compliant EU Battery Passport system."
        ),
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/applications")
def list_applications():
    """List available second-life application presets."""
    return {
        "applications": SecondLifeBid.APPLICATION_PRESETS
    }


@app.post("/validate")
def validate_battery(battery: BatteryInput):
    """
    Validate battery data without running arbitration.
    Returns a validation report showing any errors or warnings.
    """
    try:
        passport = build_passport(battery)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    agent  = DataValidationAgent()
    report = agent.validate(passport)
    return report.to_dict()


@app.post("/arbitrate")
def arbitrate(request: ArbitrateRequest):
    """
    Run the full arbitration pipeline for a battery.

    Returns a sealed verdict with decision, confidence score,
    reasoning chain, circular scores, safety certificate,
    and integrity hash chain.

    The decision enforces EU waste hierarchy law automatically:
    second life is preferred over recycling when the battery
    meets minimum technical requirements.
    """

    # ── Build passport ─────────────────────────────────────────────────
    try:
        passport = build_passport(request.battery)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # ── Validate ───────────────────────────────────────────────────────
    agent  = DataValidationAgent()
    report = agent.validate(passport)
    if not report.passed:
        raise HTTPException(
            status_code = 422,
            detail      = {
                "message":    "Battery data failed validation",
                "errors":     report.error_count,
                "validation": report.to_dict(),
            },
        )

    # ── Build carbon tracker ───────────────────────────────────────────
    try:
        api_key = ""
        if request.use_live_carbon:
            try:
                import sys, os
                sys.path.insert(0, "config")
                from config import ELECTRICITY_MAPS_API_KEY
                api_key = ELECTRICITY_MAPS_API_KEY
            except ImportError:
                pass

        tracker = DynamicCarbonTracker(
            battery_id = request.battery.battery_id,
            energy_kwh = request.battery.energy_content_kwh,
            api_key    = api_key,
            use_live   = request.use_live_carbon and bool(api_key),
        )
        tracker.add_sessions_bulk([
            {
                "session_id":  s.session_id,
                "region_code": s.region_code,
                "energy_kwh":  s.energy_kwh,
                "notes":       s.notes,
            }
            for s in request.sessions
        ])
    except Exception as e:
        raise HTTPException(
            status_code = 422,
            detail      = f"Error building carbon tracker: {str(e)}",
        )

    # ── Build bids ─────────────────────────────────────────────────────
    try:
        r  = request.recycler_bid
        recycler_bid = RecyclerBid(
            bidder_id               = r.bidder_id,
            bidder_name             = r.bidder_name,
            li_price_per_kg         = r.li_price_per_kg,
            co_price_per_kg         = r.co_price_per_kg,
            ni_price_per_kg         = r.ni_price_per_kg,
            mn_price_per_kg         = r.mn_price_per_kg,
            recovery_efficiency_pct = r.recovery_efficiency_pct,
            notes                   = r.notes,
        )
        second_life_bid = build_sl_bid(request.second_life_bid)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = 422,
            detail      = f"Error building bids: {str(e)}",
        )

    # ── Run arbitration ────────────────────────────────────────────────
    try:
        arbitrator = LifeCycleArbitrator()
        verdict    = arbitrator.arbitrate(
            passport        = passport,
            tracker         = tracker,
            recycler_bid    = recycler_bid,
            second_life_bid = second_life_bid,
            rte_pct         = request.battery.rte_pct,
        )
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Arbitration error: {str(e)}",
        )

    # ── Issue safety certificate ───────────────────────────────────────
    try:
        b    = request.battery
        cert = CertificateFactory.create_standard_cert(
            battery_id         = b.battery_id,
            passport_id        = passport.passport_id,
            soh_pct            = b.current_soh_pct,
            cycle_count        = b.cycle_count,
            max_temp_c         = b.max_temp_c,
            min_cell_voltage_v = b.min_cell_voltage_v,
            insulation_ok      = b.insulation_ok,
        )
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Certificate error: {str(e)}",
        )

    # ── Generate sealed report ─────────────────────────────────────────
    try:
        arb_report = ArbitrationReport.generate(
            passport    = passport,
            verdict     = verdict,
            tracker     = tracker,
            certificate = cert,
        )
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Report generation error: {str(e)}",
        )

    # ── Return sealed report ───────────────────────────────────────────
    return arb_report.to_dict()
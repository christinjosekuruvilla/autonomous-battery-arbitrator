# ══════════════════════════════════════════════════════════════════════
# tests/test_arbitrator.py
# ══════════════════════════════════════════════════════════════════════
# Real unit tests for the ALA system.
# Run with: pytest tests/ -v
# ══════════════════════════════════════════════════════════════════════

import pytest
from datetime import date

from ala.passport import (
    BatteryPassport,
    BatteryStrategicLayer,
    BatteryChemistry,
    CircularityLayer,
    LifecycleState,
)
from ala.carbon import DynamicCarbonTracker
from ala.bids import RecyclerBid, SecondLifeBid
from ala.scoring import CircularScore, ScoringWeights
from ala.validation import DataValidationAgent
from ala.arbitrator import (
    ArbiterDecision,
    LifeCycleArbitrator,
)
from ala.certificates import CertificateFactory


# ── Fixtures ───────────────────────────────────────────────────────────

def make_strategic(
    energy_kwh: float = 75.0,
    soh_eol:    float = 70.0,
    soh_sl:     float = 75.0,
) -> BatteryStrategicLayer:
    return BatteryStrategicLayer(
        battery_id             = "BAT-TEST-001",
        manufacturer           = "CATL",
        model_designation      = "EV-NMC-75kWh-Gen2",
        manufacturing_date     = date(2021, 6, 15),
        manufacturing_location = "DE",
        chemistry              = BatteryChemistry.NMC,
        nominal_capacity_ah    = 200.0,
        nominal_voltage_v      = 375.0,
        energy_content_kwh     = energy_kwh,
        cell_count             = 96,
        operating_temp_min_c   = -20.0,
        operating_temp_max_c   =  60.0,
        soh_eol_threshold_pct         = soh_eol,
        soh_second_life_threshold_pct = soh_sl,
        lithium_content_kg     = 8.5,
        cobalt_content_kg      = 11.2,
        nickel_content_kg      = 22.4,
        manganese_content_kg   = 7.8,
    )


def make_circularity(soh_pct: float = 90.0) -> CircularityLayer:
    return CircularityLayer(
        current_soh_pct                 = soh_pct,
        cycle_count                     = 487,
        measurement_date                = date(2026, 4, 1),
        carbon_footprint_kg_co2_per_kwh = 85.0,
        carbon_footprint_scope          = "Scope 1+2+3",
        recycled_cobalt_pct             = 12.0,
        recycled_lithium_pct            = 4.0,
        recycled_nickel_pct             = 4.0,
        lifecycle_state                 = LifecycleState.RETIREMENT_EVAL,
    )


def make_passport(soh_pct: float = 90.0) -> BatteryPassport:
    return BatteryPassport(
        make_strategic(),
        make_circularity(soh_pct),
    )


def make_tracker(battery_id: str = "BAT-TEST-001") -> DynamicCarbonTracker:
    tracker = DynamicCarbonTracker(
        battery_id = battery_id,
        energy_kwh = 75.0,
        use_live   = False,
    )
    tracker.add_sessions_bulk([
        {"session_id": "S001", "region_code": "DE", "energy_kwh": 65.2},
        {"session_id": "S002", "region_code": "NO", "energy_kwh": 71.1},
        {"session_id": "S003", "region_code": "FR", "energy_kwh": 68.4},
    ])
    return tracker


def make_recycler() -> RecyclerBid:
    return RecyclerBid(
        bidder_id               = "recycler_001",
        bidder_name             = "EuroRecycle GmbH",
        li_price_per_kg         = 13.00,
        co_price_per_kg         = 28.00,
        ni_price_per_kg         = 14.00,
        mn_price_per_kg         =  2.00,
        recovery_efficiency_pct = 0.92,
    )


def make_sl_bid(min_soh: float = 75.0) -> SecondLifeBid:
    return SecondLifeBid.for_application(
        application       = "solar_buffer_storage",
        bidder_id         = "sl_001",
        bidder_name       = "GridStore Europe BV",
        price_per_kwh_usd = 78.00,
    )


# ══════════════════════════════════════════════════════════════════════
# Passport tests
# ══════════════════════════════════════════════════════════════════════

class TestPassport:

    def test_passport_creates_integrity_hash(self):
        passport = make_passport()
        assert passport.integrity is not None
        assert len(passport.integrity.combined_sha256) == 64

    def test_passport_integrity_verifies(self):
        passport = make_passport()
        assert passport.verify_integrity() is True

    def test_remaining_energy_calculation(self):
        passport = make_passport(soh_pct=90.0)
        assert passport.remaining_energy_kwh == 67.5

    def test_second_life_eligible_above_threshold(self):
        passport = make_passport(soh_pct=80.0)
        assert passport.is_second_life_eligible is True

    def test_second_life_not_eligible_below_threshold(self):
        passport = make_passport(soh_pct=70.0)
        assert passport.is_second_life_eligible is False

    def test_invalid_soh_raises(self):
        with pytest.raises(ValueError):
            make_circularity(soh_pct=150.0)

    def test_invalid_temp_range_raises(self):
        with pytest.raises(ValueError):
            BatteryStrategicLayer(
                battery_id             = "BAT-001",
                manufacturer           = "CATL",
                model_designation      = "Test",
                manufacturing_date     = date(2021, 1, 1),
                manufacturing_location = "DE",
                chemistry              = BatteryChemistry.NMC,
                nominal_capacity_ah    = 200.0,
                nominal_voltage_v      = 375.0,
                energy_content_kwh     = 75.0,
                cell_count             = 96,
                operating_temp_min_c   = 60.0,   # min > max — invalid
                operating_temp_max_c   = -20.0,
            )

    def test_invalid_threshold_order_raises(self):
        with pytest.raises(ValueError):
            make_strategic(soh_eol=80.0, soh_sl=75.0)  # EOL > SL — invalid


# ══════════════════════════════════════════════════════════════════════
# Validation tests
# ══════════════════════════════════════════════════════════════════════

class TestValidation:

    def test_valid_passport_passes(self):
        passport = make_passport()
        agent    = DataValidationAgent()
        report   = agent.validate(passport)
        assert report.passed is True
        assert report.error_count == 0

    def test_high_soh_triggers_warning(self):
        passport = make_passport(soh_pct=99.5)
        agent    = DataValidationAgent()
        report   = agent.validate(passport)
        assert report.passed is True
        assert report.warning_count > 0

    def test_report_has_findings_list(self):
        passport = make_passport()
        agent    = DataValidationAgent()
        report   = agent.validate(passport)
        assert isinstance(report.findings, list)

    def test_report_to_dict(self):
        passport = make_passport()
        agent    = DataValidationAgent()
        report   = agent.validate(passport)
        d        = report.to_dict()
        assert "passed" in d
        assert "error_count" in d
        assert "findings" in d


# ══════════════════════════════════════════════════════════════════════
# Bid tests
# ══════════════════════════════════════════════════════════════════════

class TestBids:

    def test_recycler_material_value_positive(self):
        recycler = make_recycler()
        value    = recycler.material_value(75.0)
        assert value > 0

    def test_sl_bid_value_positive_above_min_soh(self):
        sl_bid = make_sl_bid()
        value  = sl_bid.bid_value(67.5, 90.0)
        assert value is not None
        assert value > 0

    def test_sl_bid_withdrawn_below_min_soh(self):
        sl_bid = make_sl_bid()
        value  = sl_bid.bid_value(67.5, 60.0)
        assert value is None

    def test_sl_bid_withdrawal_reason_soh(self):
        sl_bid = make_sl_bid()
        reason = sl_bid.withdrawal_reason(60.0)
        assert reason is not None
        assert "60.0%" in reason

    def test_sl_bid_preset_sets_correct_rte(self):
        sl_bid = SecondLifeBid.for_application(
            application       = "grid_frequency_response",
            bidder_id         = "test",
            bidder_name       = "Test",
            price_per_kwh_usd = 78.0,
        )
        assert sl_bid.min_rte_pct == 87.0

    def test_invalid_application_raises(self):
        with pytest.raises(ValueError):
            SecondLifeBid.for_application(
                application       = "invalid_application",
                bidder_id         = "test",
                bidder_name       = "Test",
                price_per_kwh_usd = 78.0,
            )

    def test_negative_price_raises(self):
        with pytest.raises(ValueError):
            RecyclerBid(
                bidder_id               = "r001",
                bidder_name             = "Test",
                li_price_per_kg         = -1.0,
                co_price_per_kg         = 28.0,
                ni_price_per_kg         = 14.0,
                mn_price_per_kg         =  2.0,
                recovery_efficiency_pct = 0.92,
            )


# ══════════════════════════════════════════════════════════════════════
# Scoring tests
# ══════════════════════════════════════════════════════════════════════

class TestScoring:

    def test_weights_sum_to_one(self):
        w = ScoringWeights()
        assert abs(w.financial + w.soh + w.carbon + w.hierarchy - 1.0) < 1e-6

    def test_invalid_weights_raise(self):
        with pytest.raises(ValueError):
            ScoringWeights(
                financial = 0.50,
                soh       = 0.50,
                carbon    = 0.50,
                hierarchy = 0.50,
            )

    def test_second_life_scores_higher_hierarchy(self):
        scorer = CircularScore()
        r_score = scorer.score_recycler(
            bidder_name         = "Recycler",
            financial_value_usd = 1000.0,
            max_financial_value = 5000.0,
            soh_pct             = 90.0,
            carbon_saving_pct   = 90.0,
            second_life_exists  = True,
        )
        sl_score = scorer.score_second_life(
            bidder_name         = "SL Operator",
            financial_value_usd = 5000.0,
            max_financial_value = 5000.0,
            soh_pct             = 90.0,
            carbon_saving_pct   = 90.0,
        )
        assert sl_score.hierarchy_score > r_score.hierarchy_score

    def test_composite_score_in_range(self):
        scorer   = CircularScore()
        sl_score = scorer.score_second_life(
            bidder_name         = "SL Operator",
            financial_value_usd = 5000.0,
            max_financial_value = 5000.0,
            soh_pct             = 90.0,
            carbon_saving_pct   = 90.0,
        )
        assert 0.0 <= sl_score.composite_score <= 1.0

    def test_compare_returns_winner_and_margin(self):
        scorer   = CircularScore()
        r_score  = scorer.score_recycler(
            bidder_name         = "Recycler",
            financial_value_usd = 1000.0,
            max_financial_value = 5000.0,
            soh_pct             = 90.0,
            carbon_saving_pct   = 90.0,
        )
        sl_score = scorer.score_second_life(
            bidder_name         = "SL Operator",
            financial_value_usd = 5000.0,
            max_financial_value = 5000.0,
            soh_pct             = 90.0,
            carbon_saving_pct   = 90.0,
        )
        winner, loser, margin = scorer.compare(r_score, sl_score)
        assert margin >= 0.0
        assert winner.composite_score >= loser.composite_score


# ══════════════════════════════════════════════════════════════════════
# Arbitrator tests
# ══════════════════════════════════════════════════════════════════════

class TestArbitrator:

    def test_second_life_wins_high_soh(self):
        """
        At 90% SoH with a strong second-life price advantage,
        second life should win.
        """
        passport    = make_passport(soh_pct=90.0)
        tracker     = make_tracker()
        recycler    = make_recycler()
        sl_bid      = make_sl_bid()
        arbitrator  = LifeCycleArbitrator()
        verdict     = arbitrator.arbitrate(
            passport        = passport,
            tracker         = tracker,
            recycler_bid    = recycler,
            second_life_bid = sl_bid,
        )
        assert verdict.decision in (
            ArbiterDecision.SECOND_LIFE_WINS,
            ArbiterDecision.SECOND_LIFE_OVERRIDE,
        )

    def test_recycler_wins_when_sl_bid_withdrawn(self):
        """
        When SoH drops below operator minimum, second-life bid
        is withdrawn and recycler should win by default.
        """
        passport   = make_passport(soh_pct=60.0)
        tracker    = make_tracker()
        recycler   = make_recycler()
        sl_bid     = make_sl_bid()
        arbitrator = LifeCycleArbitrator()
        verdict    = arbitrator.arbitrate(
            passport        = passport,
            tracker         = tracker,
            recycler_bid    = recycler,
            second_life_bid = sl_bid,
        )
        assert verdict.decision == ArbiterDecision.RECYCLER_DEFAULT

    def test_verdict_has_reasoning_chain(self):
        """Every verdict must include a non-empty reasoning chain."""
        passport   = make_passport()
        tracker    = make_tracker()
        arbitrator = LifeCycleArbitrator()
        verdict    = arbitrator.arbitrate(
            passport        = passport,
            tracker         = tracker,
            recycler_bid    = make_recycler(),
            second_life_bid = make_sl_bid(),
        )
        assert len(verdict.reasoning) > 0

    def test_confidence_is_valid_level(self):
        """Confidence must be HIGH, MEDIUM, or LOW."""
        passport   = make_passport()
        tracker    = make_tracker()
        arbitrator = LifeCycleArbitrator()
        verdict    = arbitrator.arbitrate(
            passport        = passport,
            tracker         = tracker,
            recycler_bid    = make_recycler(),
            second_life_bid = make_sl_bid(),
        )
        assert verdict.confidence in ("HIGH", "MEDIUM", "LOW")

    def test_confidence_margin_non_negative(self):
        passport   = make_passport()
        tracker    = make_tracker()
        arbitrator = LifeCycleArbitrator()
        verdict    = arbitrator.arbitrate(
            passport        = passport,
            tracker         = tracker,
            recycler_bid    = make_recycler(),
            second_life_bid = make_sl_bid(),
        )
        assert verdict.confidence_margin >= 0.0

    def test_verdict_to_dict_complete(self):
        """Verdict dict must contain all required keys."""
        passport   = make_passport()
        tracker    = make_tracker()
        arbitrator = LifeCycleArbitrator()
        verdict    = arbitrator.arbitrate(
            passport        = passport,
            tracker         = tracker,
            recycler_bid    = make_recycler(),
            second_life_bid = make_sl_bid(),
        )
        d = verdict.to_dict()
        required_keys = [
            "decision", "winner_name", "battery_id",
            "soh_pct", "remaining_kwh", "confidence",
            "confidence_margin", "reasoning",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ══════════════════════════════════════════════════════════════════════
# Certificate tests
# ══════════════════════════════════════════════════════════════════════

class TestCertificates:

    def test_safe_battery_gets_safe_cert(self):
        cert = CertificateFactory.create_standard_cert(
            battery_id         = "BAT-001",
            passport_id        = "EU-BP-001",
            soh_pct            = 90.0,
            cycle_count        = 487,
            max_temp_c         = 42.0,
            min_cell_voltage_v = 3.6,
            insulation_ok      = True,
        )
        assert cert.safe_for_reuse is True
        assert cert.failed_count == 0

    def test_degraded_battery_fails_cert(self):
        cert = CertificateFactory.create_standard_cert(
            battery_id         = "BAT-002",
            passport_id        = "EU-BP-002",
            soh_pct            = 55.0,   # Below 70% threshold
            cycle_count        = 487,
            max_temp_c         = 42.0,
            min_cell_voltage_v = 3.6,
            insulation_ok      = True,
        )
        assert cert.safe_for_reuse is False
        assert cert.failed_count >= 1

    def test_commitment_verifies_correctly(self):
        cert = CertificateFactory.create_standard_cert(
            battery_id         = "BAT-003",
            passport_id        = "EU-BP-003",
            soh_pct            = 90.0,
            cycle_count        = 487,
            max_temp_c         = 42.0,
            min_cell_voltage_v = 3.6,
            insulation_ok      = True,
        )
        assert cert.verify_claim("SOH_MIN", 90.0) is True

    def test_wrong_value_fails_verification(self):
        cert = CertificateFactory.create_standard_cert(
            battery_id         = "BAT-004",
            passport_id        = "EU-BP-004",
            soh_pct            = 90.0,
            cycle_count        = 487,
            max_temp_c         = 42.0,
            min_cell_voltage_v = 3.6,
            insulation_ok      = True,
        )
        assert cert.verify_claim("SOH_MIN", 80.0) is False

    def test_cert_has_five_claims(self):
        cert = CertificateFactory.create_standard_cert(
            battery_id         = "BAT-005",
            passport_id        = "EU-BP-005",
            soh_pct            = 90.0,
            cycle_count        = 487,
            max_temp_c         = 42.0,
            min_cell_voltage_v = 3.6,
            insulation_ok      = True,
        )
        assert cert.claim_count == 5

    def test_cert_hash_is_64_chars(self):
        cert = CertificateFactory.create_standard_cert(
            battery_id         = "BAT-006",
            passport_id        = "EU-BP-006",
            soh_pct            = 90.0,
            cycle_count        = 487,
            max_temp_c         = 42.0,
            min_cell_voltage_v = 3.6,
            insulation_ok      = True,
        )
        assert len(cert.cert_hash) == 64
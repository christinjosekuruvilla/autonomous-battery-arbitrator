# ══════════════════════════════════════════════════════════════════════
# ala/validation.py
# ══════════════════════════════════════════════════════════════════════
# DataValidationAgent — validates battery passport data before
# any agent acts on it.
#
# Three categories of checks:
#   1. Physical plausibility  — values within physically possible ranges
#   2. Regulatory compliance  — values meeting EU Battery Reg thresholds
#   3. Internal consistency   — values that must logically relate
#
# Production gaps (thesis future work):
#   - Schema validation against official DIN DKE SPEC 99100 JSON schema
#   - Cross-battery fleet consistency checks
#   - BMS sensor confidence intervals
#   - Catena-X data sovereignty verification
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ala.passport import BatteryPassport


# ── Finding ────────────────────────────────────────────────────────────

@dataclass
class ValidationFinding:
    """A single error or warning from the DataValidationAgent."""
    level:   str   # "ERROR" or "WARNING"
    field:   str   # Which field triggered this finding
    message: str   # Human-readable description
    value:   Any   # The actual value that caused the finding

    def __str__(self) -> str:
        icon = "❌" if self.level == "ERROR" else "⚠️ "
        return (
            f"  {icon} [{self.level}] {self.field}: "
            f"{self.message} (got: {self.value})"
        )


# ── Report ─────────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    """
    Complete output of a DataValidationAgent.validate() call.

    passed:   True only when there are zero ERROR-level findings.
              WARNING findings do not block arbitration.
    findings: All errors and warnings in order of severity.
    """
    passed:   bool
    findings: list[ValidationFinding]

    @property
    def errors(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.level == "ERROR"]

    @property
    def warnings(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.level == "WARNING"]

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def print_report(self) -> None:
        status = "✅ PASSED" if self.passed else "❌ FAILED"
        print("━" * 62)
        print("  DATA VALIDATION REPORT")
        print("━" * 62)
        print(f"  Result   : {status}")
        print(f"  Errors   : {self.error_count}")
        print(f"  Warnings : {self.warning_count}")

        if not self.findings:
            print()
            print("  All checks passed — no issues found.")
        else:
            print()
            print("  Findings:")
            for finding in self.findings:
                print(str(finding))

        if not self.passed:
            print()
            print("  ⛔ Arbitration blocked — resolve all ERRORs.")
        elif self.warning_count > 0:
            print()
            print("  ⚠️  Arbitration allowed — review WARNINGs.")

        print("━" * 62)

    def to_dict(self) -> dict:
        return {
            "passed":        self.passed,
            "error_count":   self.error_count,
            "warning_count": self.warning_count,
            "findings": [
                {
                    "level":   f.level,
                    "field":   f.field,
                    "message": f.message,
                    "value":   str(f.value),
                }
                for f in self.findings
            ],
        }


# ── Agent ──────────────────────────────────────────────────────────────

class DataValidationAgent:
    """
    Agent 0 — The Gatekeeper.

    Validates BatteryPassport data before any other agent acts.
    Runs checks across three categories:

      Category 1 — Physical plausibility
        Values within physically possible ranges.

      Category 2 — Regulatory compliance
        Values meeting EU Battery Regulation thresholds.
        Art. 8 recycled content percentage bounds.

      Category 3 — Internal consistency
        Values that must logically relate to each other.
        Energy content vs Ah x V calculation.
        SoH threshold ordering.
        Manufacturing date not in future.

    Usage:
        agent  = DataValidationAgent()
        report = agent.validate(passport)

        if not report.passed:
            report.print_report()
            raise ValueError("Validation failed — arbitration blocked")
    """

    def validate(self, passport: BatteryPassport) -> ValidationReport:
        """
        Run all validation checks on a BatteryPassport.
        Returns a ValidationReport — never raises an exception itself.
        The caller decides what to do with errors and warnings.
        """
        findings: list[ValidationFinding] = []
        s = passport.strategic
        c = passport.circularity

        # ── Category 1: Physical plausibility ─────────────────────────

        # SoH must be 0–100%
        if not (0.0 <= c.current_soh_pct <= 100.0):
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "current_soh_pct",
                message = "SoH must be between 0% and 100%",
                value   = c.current_soh_pct,
            ))
        elif c.current_soh_pct > 99.0:
            findings.append(ValidationFinding(
                level   = "WARNING",
                field   = "current_soh_pct",
                message = "SoH above 99% is unusual — verify BMS calibration",
                value   = c.current_soh_pct,
            ))

        # Energy content must be positive
        if s.energy_content_kwh <= 0:
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "energy_content_kwh",
                message = "Energy content must be greater than zero",
                value   = s.energy_content_kwh,
            ))

        # Nominal capacity must be positive
        if s.nominal_capacity_ah <= 0:
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "nominal_capacity_ah",
                message = "Nominal capacity must be greater than zero",
                value   = s.nominal_capacity_ah,
            ))

        # Nominal voltage must be positive
        if s.nominal_voltage_v <= 0:
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "nominal_voltage_v",
                message = "Nominal voltage must be greater than zero",
                value   = s.nominal_voltage_v,
            ))

        # Carbon footprint must be positive
        if c.carbon_footprint_kg_co2_per_kwh <= 0:
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "carbon_footprint_kg_co2_per_kwh",
                message = "Carbon footprint must be greater than zero",
                value   = c.carbon_footprint_kg_co2_per_kwh,
            ))

        # Temperature range must be logical
        if s.operating_temp_min_c >= s.operating_temp_max_c:
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "operating_temp_range",
                message = "Min operating temp must be less than max",
                value   = (
                    f"min:{s.operating_temp_min_c} "
                    f"max:{s.operating_temp_max_c}"
                ),
            ))

        # ── Category 2: Regulatory compliance ─────────────────────────

        # Recycled content cannot exceed 100%
        for field_name, value in [
            ("recycled_cobalt_pct",  c.recycled_cobalt_pct),
            ("recycled_lithium_pct", c.recycled_lithium_pct),
            ("recycled_nickel_pct",  c.recycled_nickel_pct),
        ]:
            if not (0.0 <= value <= 100.0):
                findings.append(ValidationFinding(
                    level   = "ERROR",
                    field   = field_name,
                    message = "Recycled content must be 0–100%",
                    value   = value,
                ))

        # Cycle count must be non-negative
        if c.cycle_count < 0:
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "cycle_count",
                message = "Cycle count cannot be negative",
                value   = c.cycle_count,
            ))

        # ── Category 3: Internal consistency ──────────────────────────

        # Energy content should approximately equal Ah x V / 1000
        # Allow 10% tolerance for measurement conditions
        expected_kwh = (s.nominal_capacity_ah * s.nominal_voltage_v) / 1000
        actual_kwh   = s.energy_content_kwh
        if expected_kwh > 0:
            deviation = abs(actual_kwh - expected_kwh) / expected_kwh
            if deviation > 0.10:
                findings.append(ValidationFinding(
                    level   = "WARNING",
                    field   = "energy_content_kwh",
                    message = (
                        f"Energy content {actual_kwh} kWh deviates "
                        f"{deviation*100:.1f}% from calculated "
                        f"{expected_kwh:.1f} kWh (Ah x V / 1000)"
                    ),
                    value   = actual_kwh,
                ))

        # SoH thresholds must be logically ordered
        if s.soh_eol_threshold_pct >= s.soh_second_life_threshold_pct:
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "soh_thresholds",
                message = (
                    "EOL threshold must be below second-life threshold"
                ),
                value   = (
                    f"eol:{s.soh_eol_threshold_pct}% "
                    f"second_life:{s.soh_second_life_threshold_pct}%"
                ),
            ))

        # Manufacturing date cannot be in the future
        if s.manufacturing_date > date.today():
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "manufacturing_date",
                message = "Manufacturing date cannot be in the future",
                value   = s.manufacturing_date.isoformat(),
            ))

        # Passport ID must not be empty
        if not passport.passport_id or not passport.passport_id.strip():
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "passport_id",
                message = "Passport ID cannot be empty",
                value   = passport.passport_id,
            ))

        # Integrity must be verified
        if not passport.verify_integrity():
            findings.append(ValidationFinding(
                level   = "ERROR",
                field   = "integrity",
                message = "Passport integrity check failed — data may have been tampered with",
                value   = "hash mismatch",
            ))

        error_count = sum(1 for f in findings if f.level == "ERROR")
        return ValidationReport(
            passed   = error_count == 0,
            findings = findings,
        )
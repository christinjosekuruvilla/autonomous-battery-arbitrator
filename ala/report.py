# ══════════════════════════════════════════════════════════════════════
# ala/report.py
# ══════════════════════════════════════════════════════════════════════
# ArbitrationReport — sealed, exportable, auditable report.
#
# Chains onto the passport SHA-256 hash so any alteration
# to either the passport or the report is immediately detectable.
#
# Production gaps (thesis future work):
#   - Database persistence with audit log
#   - Regulatory submission format (EU Battery Passport registry)
#   - Digital signature by authorised arbitration body
#   - Multi-party report signing workflow
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ala.arbitrator import RetirementVerdict
from ala.carbon import DynamicCarbonTracker
from ala.certificates import PrivacyPreservingCert
from ala.passport import BatteryPassport


# ── Report ─────────────────────────────────────────────────────────────

@dataclass
class ArbitrationReport:
    """
    Sealed arbitration report chaining onto the battery passport.

    The report hash is computed over the full report payload
    including the passport hash — so any change to either
    the passport or the report content breaks the chain.

    Note: This is standard SHA-256 used for tamper detection.
    It is not a formally compliant EU Battery Passport registry
    submission — that would require PKI signing and registry
    integration as future work.
    """
    report_id:       str
    passport_id:     str
    passport_hash:   str    # Passport combined SHA-256 at time of report
    verdict:         RetirementVerdict
    carbon_record:   DynamicCarbonTracker
    certificate:     PrivacyPreservingCert
    generated_at:    str
    report_hash:     str    # SHA-256 of full report payload
    regulation:      str = "EU Battery Regulation 2023/1542"
    system_version:  str = "ALA v2.0 — proof-of-concept"

    @classmethod
    def generate(
        cls,
        passport:    BatteryPassport,
        verdict:     RetirementVerdict,
        tracker:     DynamicCarbonTracker,
        certificate: PrivacyPreservingCert,
    ) -> "ArbitrationReport":
        """
        Generate a sealed arbitration report.

        Computes a SHA-256 hash over the full report payload
        including the passport hash to form the integrity chain.
        """
        generated_at  = datetime.now(timezone.utc).isoformat()
        report_id     = f"ALA-{generated_at[:10]}-{passport.strategic.battery_id}"
        passport_hash = passport.integrity.combined_sha256

        # Build payload for hashing
        payload = {
            "report_id":     report_id,
            "passport_id":   passport.passport_id,
            "passport_hash": passport_hash,
            "generated_at":  generated_at,
            "verdict":       verdict.to_dict(),
            "carbon_record": tracker.to_dict(),
            "certificate":   certificate.to_dict(),
        }
        report_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

        return cls(
            report_id     = report_id,
            passport_id   = passport.passport_id,
            passport_hash = passport_hash,
            verdict       = verdict,
            carbon_record = tracker,
            certificate   = certificate,
            generated_at  = generated_at,
            report_hash   = report_hash,
        )

    def verify_chain(self, passport: BatteryPassport) -> bool:
        """
        Verify that the report still chains onto the passport.

        Returns True if:
          1. The passport hash matches what was recorded at report time
          2. The passport integrity is still intact
        """
        current_hash = passport.integrity.combined_sha256
        return (
            current_hash == self.passport_hash
            and passport.verify_integrity()
        )

    def verify_report_hash(self) -> bool:
        """
        Verify the report has not been tampered with.
        Recomputes the hash and compares to stored value.
        """
        payload = {
            "report_id":     self.report_id,
            "passport_id":   self.passport_id,
            "passport_hash": self.passport_hash,
            "generated_at":  self.generated_at,
            "verdict":       self.verdict.to_dict(),
            "carbon_record": self.carbon_record.to_dict(),
            "certificate":   self.certificate.to_dict(),
        }
        recomputed = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        return recomputed == self.report_hash

    def to_dict(self) -> dict:
        return {
            "report_id":      self.report_id,
            "generated_at":   self.generated_at,
            "report_hash":    self.report_hash,
            "regulation":     self.regulation,
            "_system":        self.system_version,
            "passport_id":    self.passport_id,
            "passport_hash":  self.passport_hash,
            "battery":        {
                "battery_id":    self.verdict.battery_id,
                "soh_pct":       self.verdict.soh_pct,
                "remaining_kwh": self.verdict.remaining_kwh,
            },
            "carbon_record":  self.carbon_record.to_dict(),
            "verdict":        self.verdict.to_dict(),
            "certificate":    self.certificate.to_dict(),
        }

    def export_json(self, path: str) -> Path:
        """
        Export the sealed report to a JSON file.
        Returns the path of the written file.
        """
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return output

    def print_summary(self) -> None:
        v = self.verdict
        chain_ok  = self.verify_report_hash()
        print("━" * 62)
        print("  ARBITRATION REPORT SUMMARY")
        print("━" * 62)
        print(f"  Report ID      : {self.report_id}")
        print(f"  Generated at   : {self.generated_at}")
        print(f"  Regulation     : {self.regulation}")
        print()
        print(f"  Battery        : {v.battery_id}")
        print(f"  SoH            : {v.soh_pct}%")
        print(f"  Remaining kWh  : {v.remaining_kwh} kWh")
        print(f"  Lifetime CO2   : {v.lifetime_kg_co2} kg")
        print(f"  Carbon saving  : {v.carbon_saving_pct}% vs new pack")
        print()
        print(f"  Recycler offer : ${v.recycler_offer:>8.2f}")
        if v.second_life_offer:
            print(f"  2nd-life offer : ${v.second_life_offer:>8.2f}")
        else:
            print(f"  2nd-life offer : WITHDRAWN")
        print()
        print(f"  Decision       : {v.decision.value}")
        print(f"  Winner         : {v.winner_name}")
        print(f"  Confidence     : {v.confidence_icon}  "
              f"{v.confidence}  (margin: {v.confidence_margin:.4f})")
        print(f"  Safe for reuse : "
              f"{'✅ YES' if self.certificate.safe_for_reuse else '❌ NO'}")
        print()
        print(f"  Passport hash  : {self.passport_hash[:32]}...")
        print(f"  Report hash    : {self.report_hash[:32]}...")
        print(f"  Chain intact   : "
              f"{'✅ VERIFIED' if chain_ok else '❌ BROKEN'}")
        print("━" * 62)

    def print_integrity_check(
        self,
        passport: BatteryPassport,
    ) -> None:
        """Print a detailed integrity verification."""
        chain_ok  = self.verify_chain(passport)
        report_ok = self.verify_report_hash()
        passport_ok = passport.verify_integrity()

        print("━" * 62)
        print("  INTEGRITY CHAIN VERIFICATION")
        print("━" * 62)
        print(f"  Passport integrity   : "
              f"{'✅ VERIFIED' if passport_ok else '❌ BROKEN'}")
        print(f"  Report hash valid    : "
              f"{'✅ VERIFIED' if report_ok else '❌ BROKEN'}")
        print(f"  Chain intact         : "
              f"{'✅ VERIFIED' if chain_ok else '❌ BROKEN'}")
        print()
        print(f"  Passport hash  : {self.passport_hash[:32]}...")
        print(f"  Report hash    : {self.report_hash[:32]}...")
        print("━" * 62)
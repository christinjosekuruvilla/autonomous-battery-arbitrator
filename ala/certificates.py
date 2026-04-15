# ══════════════════════════════════════════════════════════════════════
# ala/certificates.py
# ══════════════════════════════════════════════════════════════════════
# Privacy-preserving safety certificates for battery reuse.
#
# Uses SHA-256 salted commitment scheme to prove safety claims
# without exposing raw sensor data.
#
# How it works:
#   1. For each safety claim, combine the raw value with a
#      random salt and hash it with SHA-256
#   2. The certificate contains only the hashes — not the values
#   3. A verifier can check a claim by hashing value + salt
#      and comparing to the stored commitment
#   4. Without the salt, the raw value cannot be recovered
#
# Production gaps (thesis future work):
#   - Zero-knowledge proofs for stronger privacy guarantees
#   - PKI-based certificate signing by notified bodies
#   - EU Battery Regulation Art. 65 data authenticity compliance
#   - Certificate revocation mechanism
#   - Actor-specific disclosure tiers
# ══════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Safety claim ───────────────────────────────────────────────────────

@dataclass
class SafetyClaim:
    """
    A single safety assertion about a battery.

    The raw value is committed to via SHA-256 + salt.
    Only the commitment hash is stored in the certificate —
    not the raw sensor reading.
    """
    claim_id:   str    # Unique identifier for this claim type
    label:      str    # Human-readable claim description
    passes:     bool   # Whether the claim passes the safety threshold
    commitment: str    # SHA-256(salt + str(raw_value))
    salt:       str    # Random salt used in commitment (keep private)

    @classmethod
    def create(
        cls,
        claim_id:  str,
        label:     str,
        value:     Any,
        threshold: Any,
        passes:    bool,
    ) -> "SafetyClaim":
        """
        Create a safety claim with a fresh random salt.

        The salt is generated fresh for each claim.
        Store the salt securely — it is needed to verify the claim.
        """
        salt       = os.urandom(32).hex()
        commitment = hashlib.sha256(
            f"{salt}{str(value)}".encode()
        ).hexdigest()
        return cls(
            claim_id   = claim_id,
            label      = label,
            passes     = passes,
            commitment = commitment,
            salt       = salt,
        )

    def verify(self, raw_value: Any) -> bool:
        """
        Verify a claim by recomputing the commitment.
        Returns True if raw_value matches the stored commitment.
        """
        recomputed = hashlib.sha256(
            f"{self.salt}{str(raw_value)}".encode()
        ).hexdigest()
        return recomputed == self.commitment

    def to_dict(self, include_salt: bool = False) -> dict:
        """
        Serialise the claim.
        Never include the salt in public-facing exports.
        """
        result = {
            "claim_id":   self.claim_id,
            "label":      self.label,
            "passes":     self.passes,
            "commitment": self.commitment,
        }
        if include_salt:
            result["salt"] = self.salt
        return result


# ── Certificate ────────────────────────────────────────────────────────

@dataclass
class PrivacyPreservingCert:
    """
    Privacy-preserving safety certificate for battery reuse.

    Contains SHA-256 salted commitments for safety claims.
    Raw sensor values are never stored in the certificate.

    safe_for_reuse is True only when ALL claims pass.

    Note: This is a proof-of-concept implementation using
    standard SHA-256 commitment schemes. Production would
    require PKI-based signing by notified bodies and
    compliance with EU Battery Regulation Art. 65.
    """
    battery_id:     str
    passport_id:    str
    claims:         list[SafetyClaim]
    issued_at_utc:  str
    cert_hash:      str   # SHA-256 of all commitment hashes combined

    @property
    def safe_for_reuse(self) -> bool:
        return all(c.passes for c in self.claims)

    @property
    def claim_count(self) -> int:
        return len(self.claims)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.claims if c.passes)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.claims if not c.passes)

    @classmethod
    def issue(
        cls,
        battery_id:  str,
        passport_id: str,
        claims:      list[SafetyClaim],
    ) -> "PrivacyPreservingCert":
        """
        Issue a certificate from a list of safety claims.
        Computes a combined hash over all commitment hashes.
        """
        issued_at = datetime.now(timezone.utc).isoformat()
        combined  = hashlib.sha256(
            "".join(c.commitment for c in claims).encode()
        ).hexdigest()
        return cls(
            battery_id    = battery_id,
            passport_id   = passport_id,
            claims        = claims,
            issued_at_utc = issued_at,
            cert_hash     = combined,
        )

    def verify_claim(self, claim_id: str, raw_value: Any) -> bool:
        """
        Verify a specific claim by providing the raw value.
        Returns True if the commitment matches.
        """
        for claim in self.claims:
            if claim.claim_id == claim_id:
                return claim.verify(raw_value)
        raise ValueError(f"Claim '{claim_id}' not found in certificate")

    def print_certificate(self) -> None:
        status = "✅ SAFE FOR REUSE" if self.safe_for_reuse else "❌ NOT SAFE"
        print("━" * 62)
        print("  PRIVACY-PRESERVING SAFETY CERTIFICATE")
        print("━" * 62)
        print(f"  Battery ID   : {self.battery_id}")
        print(f"  Passport ID  : {self.passport_id}")
        print(f"  Issued at    : {self.issued_at_utc}")
        print(f"  Status       : {status}")
        print(f"  Claims       : {self.passed_count}/{self.claim_count} passed")
        print()
        print("  Commitments (raw values not stored):")
        for claim in self.claims:
            icon = "✅" if claim.passes else "❌"
            print(f"    {icon} {claim.label}")
            print(f"       {claim.commitment[:40]}...")
        print()
        print(f"  Certificate hash: {self.cert_hash[:40]}...")
        print("━" * 62)

    def to_dict(self, include_salts: bool = False) -> dict:
        return {
            "battery_id":    self.battery_id,
            "passport_id":   self.passport_id,
            "safe_for_reuse": self.safe_for_reuse,
            "claim_count":   self.claim_count,
            "passed_count":  self.passed_count,
            "failed_count":  self.failed_count,
            "issued_at_utc": self.issued_at_utc,
            "cert_hash":     self.cert_hash,
            "claims": [
                c.to_dict(include_salt=include_salts)
                for c in self.claims
            ],
        }


# ── Certificate factory ────────────────────────────────────────────────

class CertificateFactory:
    """
    Creates standard safety certificates for EV battery reuse.

    Standard claims cover the five key safety dimensions
    required for second-life deployment.

    In production, values would come from real BMS sensor
    readings rather than being passed as arguments.
    """

    @staticmethod
    def create_standard_cert(
        battery_id:         str,
        passport_id:        str,
        soh_pct:            float,
        cycle_count:        int,
        max_temp_c:         float,
        min_cell_voltage_v: float,
        insulation_ok:      bool,
    ) -> PrivacyPreservingCert:
        """
        Issue a standard five-claim safety certificate.

        Claims:
          1. SoH above minimum reuse threshold (70%)
          2. Cycle count within safe operating range (< 3000)
          3. Maximum operating temperature within spec (< 55°C)
          4. Minimum cell voltage above cutoff (> 2.8V)
          5. Insulation resistance passes safety check
        """
        claims = [
            SafetyClaim.create(
                claim_id  = "SOH_MIN",
                label     = "State of Health above reuse minimum (70%)",
                value     = soh_pct,
                threshold = 70.0,
                passes    = soh_pct >= 70.0,
            ),
            SafetyClaim.create(
                claim_id  = "CYCLE_MAX",
                label     = "Cycle count within safe range (< 3000)",
                value     = cycle_count,
                threshold = 3000,
                passes    = cycle_count < 3000,
            ),
            SafetyClaim.create(
                claim_id  = "TEMP_MAX",
                label     = "Peak operating temperature within spec (< 55°C)",
                value     = max_temp_c,
                threshold = 55.0,
                passes    = max_temp_c < 55.0,
            ),
            SafetyClaim.create(
                claim_id  = "CELL_VOLT_MIN",
                label     = "Minimum cell voltage above cutoff (> 2.8V)",
                value     = min_cell_voltage_v,
                threshold = 2.8,
                passes    = min_cell_voltage_v > 2.8,
            ),
            SafetyClaim.create(
                claim_id  = "INSULATION",
                label     = "Insulation resistance passes safety check",
                value     = insulation_ok,
                threshold = True,
                passes    = insulation_ok,
            ),
        ]
        return PrivacyPreservingCert.issue(
            battery_id  = battery_id,
            passport_id = passport_id,
            claims      = claims,
        )
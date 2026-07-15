"""Fake CRM server for E2E testing.

Endpoints:
  GET  /api/customers?email=<sender_email>   → customer lookup (for identity phase)
  GET  /api/claims/<claim_number>             → claim status (for intent tool)
  POST /api/claims/<claim_number>/escalate    → escalate claim (another intent tool)
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

CUSTOMERS = {
    "thomas.mueller@example.com": {
        "customerFound": True,
        "lookupEmail": "thomas.mueller@example.com",
        "customerId": "CUST-4821",
        "fullName": "Thomas Müller",
        "organization": "Müller & Partner GmbH",
        "status": "active",
        "segment": "premium",
        "preferredLanguage": "de",
        "openMatters": ["CLM-2024-0087", "CLM-2024-0112"],
        "notes": "Long-standing client since 2018. Specializes in commercial property insurance.",
    },
    "anna.schmidt@example.com": {
        "customerFound": True,
        "lookupEmail": "anna.schmidt@example.com",
        "customerId": "CUST-7733",
        "fullName": "Anna Schmidt",
        "organization": "Schmidt Logistik AG",
        "status": "active",
        "segment": "standard",
        "preferredLanguage": "de",
        "openMatters": ["CLM-2024-0203"],
        "notes": "Fleet insurance client. Renewed policy in January 2024.",
    },
}

POLICIES = {
    "POL-2023-1001": {
        "policyNumber": "POL-2023-1001",
        "customerId": "CUST-4821",
        "type": "commercial_property",
        "status": "active",
        "startDate": "2023-01-01",
        "endDate": "2025-12-31",
        "premium": 4800,
        "premiumCurrency": "EUR",
        "premiumFrequency": "annual",
        "coverageLimit": 2000000,
        "deductible": 5000,
        "insuredObjects": [
            "Warehouse Zürich-Nord (Industriestrasse 42)",
            "Office building Zürich-City (Bahnhofstrasse 10)",
        ],
        "additionalCoverages": ["natural_hazards", "business_interruption", "glass_breakage"],
        "lastClaimDate": "2024-03-16",
        "renewalDate": "2025-12-31",
        "notes": "Multi-year contract with 5% loyalty discount applied.",
    },
    "POL-2023-1002": {
        "policyNumber": "POL-2023-1002",
        "customerId": "CUST-4821",
        "type": "commercial_liability",
        "status": "active",
        "startDate": "2023-06-01",
        "endDate": "2025-05-31",
        "premium": 2400,
        "premiumCurrency": "EUR",
        "premiumFrequency": "annual",
        "coverageLimit": 5000000,
        "deductible": 1000,
        "insuredObjects": ["General commercial liability for Müller & Partner GmbH"],
        "additionalCoverages": ["product_liability", "professional_indemnity"],
        "lastClaimDate": "2024-02-28",
        "renewalDate": "2025-05-31",
        "notes": "Includes worldwide coverage for business travel.",
    },
    "POL-2024-2001": {
        "policyNumber": "POL-2024-2001",
        "customerId": "CUST-7733",
        "type": "fleet_vehicle",
        "status": "active",
        "startDate": "2024-01-15",
        "endDate": "2025-01-14",
        "premium": 12000,
        "premiumCurrency": "EUR",
        "premiumFrequency": "annual",
        "coverageLimit": 500000,
        "deductible": 2000,
        "insuredObjects": [
            "Fleet of 8 delivery vehicles (Schmidt Logistik AG)",
        ],
        "additionalCoverages": ["roadside_assistance", "replacement_vehicle", "cargo_insurance"],
        "lastClaimDate": "2024-04-01",
        "renewalDate": "2025-01-14",
        "notes": "Fleet discount 15%. Annual vehicle inspection required for renewal.",
    },
}

# Map customer IDs to their policy numbers for lookup
CUSTOMER_POLICIES = {}
for _pol_num, _pol_data in POLICIES.items():
    cid = _pol_data["customerId"]
    CUSTOMER_POLICIES.setdefault(cid, []).append(_pol_num)

CLAIMS = {
    "CLM-2024-0087": {
        "claimNumber": "CLM-2024-0087",
        "status": "under_review",
        "type": "property_damage",
        "description": "Water damage to warehouse roof after storm on 2024-03-15",
        "filedDate": "2024-03-16",
        "lastUpdate": "2024-04-10",
        "assignedAdjuster": "Dr. Klaus Weber",
        "estimatedAmount": 45000,
        "currency": "EUR",
        "nextSteps": "Awaiting independent assessor report. Expected by 2024-04-25.",
    },
    "CLM-2024-0112": {
        "claimNumber": "CLM-2024-0112",
        "status": "approved",
        "type": "liability",
        "description": "Third-party liability claim from delivery vehicle incident",
        "filedDate": "2024-02-28",
        "lastUpdate": "2024-04-05",
        "assignedAdjuster": "Maria Fischer",
        "estimatedAmount": 12500,
        "currency": "EUR",
        "nextSteps": "Payment processing initiated. Funds will be transferred within 5 business days.",
    },
    "CLM-2024-0203": {
        "claimNumber": "CLM-2024-0203",
        "status": "pending_documents",
        "type": "vehicle_damage",
        "description": "Collision damage to fleet vehicle (plate: ZH-123456)",
        "filedDate": "2024-04-01",
        "lastUpdate": "2024-04-08",
        "assignedAdjuster": "Dr. Klaus Weber",
        "estimatedAmount": 8200,
        "currency": "EUR",
        "nextSteps": "Missing: police report and repair estimate from authorized workshop.",
    },
}


class FakeCRMHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        # Customer lookup
        if parsed.path == "/api/customers":
            email = qs.get("email", [None])[0]
            if not email:
                self._send_json({"error": "email parameter required"}, 400)
                return
            customer = CUSTOMERS.get(email.lower())
            if customer:
                self._send_json(customer)
            else:
                self._send_json({
                    "customerFound": False,
                    "lookupEmail": email,
                })
            return

        # Policy lookup by customer_id
        if parsed.path == "/api/policies":
            customer_id = qs.get("customer_id", [None])[0]
            if not customer_id:
                self._send_json({"error": "customer_id parameter required"}, 400)
                return
            policy_numbers = CUSTOMER_POLICIES.get(customer_id, [])
            policies = [POLICIES[pn] for pn in policy_numbers]
            self._send_json({"customerId": customer_id, "policies": policies})
            return

        # Specific policy lookup
        if parsed.path.startswith("/api/policies/") and not parsed.path.startswith("/api/policies?"):
            parts = parsed.path.split("/")
            policy_number = parts[3] if len(parts) > 3 else None
            if not policy_number or policy_number not in POLICIES:
                self._send_json({"error": f"Policy {policy_number} not found"}, 404)
                return
            self._send_json(POLICIES[policy_number])
            return

        # Claim status lookup
        if parsed.path.startswith("/api/claims/"):
            parts = parsed.path.split("/")
            claim_number = parts[3] if len(parts) > 3 else None
            if not claim_number or claim_number not in CLAIMS:
                self._send_json({"error": f"Claim {claim_number} not found"}, 404)
                return
            self._send_json(CLAIMS[claim_number])
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)

        # Claim escalation
        if parsed.path.startswith("/api/claims/") and parsed.path.endswith("/escalate"):
            parts = parsed.path.split("/")
            claim_number = parts[3] if len(parts) > 3 else None
            if claim_number not in CLAIMS:
                self._send_json({"error": f"Claim {claim_number} not found"}, 404)
                return
            self._send_json({
                "status": "escalated",
                "claimNumber": claim_number,
                "message": f"Claim {claim_number} has been escalated to senior adjuster.",
            })
            return

        self._send_json({"error": "Not found"}, 404)

    def log_message(self, fmt, *args):
        print(f"[FakeCRM] {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 3000), FakeCRMHandler)
    print("[FakeCRM] Starting on http://localhost:3000")
    print("[FakeCRM] Endpoints:")
    print("  GET  /api/customers?email=<email>")
    print("  GET  /api/policies?customer_id=<customer_id>")
    print("  GET  /api/policies/<policy_number>")
    print("  GET  /api/claims/<claim_number>")
    print("  POST /api/claims/<claim_number>/escalate")
    server.serve_forever()

"""Versioned, pure configuration for the screening decision rules."""

RULES_VERSION = "2026-11-07.v1"

HIGH_RISK_LIFETIME_PCT = 20.0
HIGH_RISK_RADIATION_MAX_AGE = 30
URGENT_BIRADS = frozenset({4, 5, 6})
RECALL_BIRADS = 0
SHORT_INTERVAL_BIRADS = 3


# services/scoring_config.py
from __future__ import annotations

# --- Normalization thresholds (tunable but kept in one place) ---
P0, P1 = 1.6, 2.4
S0, S1 = 3.5, 6.0
W0, W1 = 0.25, 0.60
A0, A1 = 0.06, 0.18

PR0, PR1 = 2.1, 2.7
SR0, SR1 = 3.8, 5.5
WR0, WR1 = 0.30, 0.70
AR0, AR1 = 0.08, 0.22

V0, V1 = 0.25, 0.70

HB0 = 1.35
HIND_ASYM0 = 0.14
FORE_ASYM0 = 0.14

DELTA_MAX = 18.0

CAL_A0 = -0.15
CAL_A1 = 1.00
CAL_A2 = 0.80

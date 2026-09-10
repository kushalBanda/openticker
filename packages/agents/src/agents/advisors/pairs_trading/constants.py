# Bounds grounded in the Gatev/Goetzmann/Rouwenhorst pairs-trading literature,
# not chosen for maximum Advisor flexibility.
ENTRY_Z_MIN, ENTRY_Z_MAX = 1.5, 3.5
FORMATION_MONTHS_MIN, FORMATION_MONTHS_MAX = 3, 12
TRADING_MONTHS_MIN, TRADING_MONTHS_MAX = 1, 6
BUFFER_MIN, BUFFER_MAX = 0.05, 0.25

# Fixed size of the candidate window shown to the Advisor each cycle
# (CONTEXT.md's "Candidate window"), not derived from any prior decision.
CANDIDATE_WINDOW_SIZE = 30

# Float slack allowed when checking selected weights + buffer reconcile to 1.0.
CAPITAL_RECONCILE_TOLERANCE = 0.01

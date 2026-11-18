"""Global nailing / materialization policy.

Only ONE policy is implemented.  Redeem events are the source of truth in the
lake; a redeem fact is derived.  Facts are created *only* inside the nail
transaction, as batch details, and never on event ingest and never in a
background/materialize-elsewhere path.
"""

SEAL_POLICY = "materialize_on_nail"
SEAL_POLICY_LABEL = "钉扎时补物化"

# Redeem events are never materialized when they are written to the lake.
MATERIALIZE_ON_INGEST = False

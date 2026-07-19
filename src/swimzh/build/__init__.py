"""The offline build seam: normalize -> reconcile -> (compose) -> materialize.

`normalize` is the one cleaning home; `reconcile` is the sole producer of a canonical
`PoolId`; `seed` assembles the DB-enforced identity spine (the `pool` table + its
alias/xref crosswalk) from the committed catalog + curated inputs.
"""

---
type: entity
created: 2026-07-19
links: ["[[2026-07-19-rich-pool-domain]]"]
---

# LockerOption

One locker offering at a facility (wardrobe / valuables / laundry category).
Cost is modelled as ORTHOGONAL optionals — `fee_chf`, `deposit_chf`, `period`
— not a tagged union, because real rows combine them freely
(`gratis, plus Depot Fr. 5.–` = free usage + refundable deposit;
`Wäschefach (1 Jahr) Fr. 400.–` = fee + rental period).

`raw` keeps the exact source row for audit/reparse. `mechanism` (coin/key/…)
is usually unstated → `None`.

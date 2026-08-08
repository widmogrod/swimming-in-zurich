---
type: entity
name: rental-item
created: 2026-08-08
links: ["[[2026-08-08-mietobjekt-extraction-plan]]", "[[locker-option]]"]
---

# RentalItem

One rentable object at a facility — the half of the `Mietobjekt | Preis` table that
[[locker-option]] cannot hold. `LockerCategory` is `WARDROBE | VALUABLES | LAUNDRY`; the same
table also rents towels, swimwear and goggles (`Badetuch | Fr. 3.–, plus Depot Fr. 20.–`), and a
towel is not a locker. Forcing it into `LockerCategory` would make the name lie; dropping it is
the compression the project forbids.

`kind: TOWEL | SWIMWEAR | GOGGLES | OTHER`, with the same orthogonal cost axes as
[[locker-option]] (`fee_chf` / `deposit_chf`, freely combined by the source rows) and the same
`raw` audit string. **`OTHER` is the no-drop guarantee**: a label the router does not recognise
still lands, kind-tagged as unclassified, with the original text preserved — the same idiom as
`ClosureCode.UNMAPPED`.

Lives on `Facility.rentals`, additive and popped when empty, so blobs without rentals are
byte-identical to before the field existed.

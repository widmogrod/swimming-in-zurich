---
type: entity
name: session-access
created: 2026-08-05
links: ["[[2026-08-05-school-access-vocabulary-plan]]", "[[basin]]"]
---

# SessionAccess

Who a swim session is for. A **closed** tagged union in `domain/access.py`, matched
exhaustively with `assert_never` in both `access_info` (what it means) and `eligibility`
(may this person attend). Closedness is the point: adding a member is a compiler error at
every decision site, so a new access kind cannot be silently folded into `PublicSwim`.

Members fall into three groups: **open to anyone** (`PublicSwim`, `LaneSwim`, `FamilyTime`),
**restricted by who you are** (`WomenOnly`, `GirlsOnly`, `GenderDiverse`, `SeniorsOnly`,
`AdultsOnly`, `AccompaniedChildren`), and **not public at all** (`SchoolReserved`,
`ClubReserved`).

Two rules govern the restricted group:

- **Never invent a boundary.** An age bound is carried only where the source states one
  (`GenderDiverse(min_age=16)` from *"ab 16 Jahren"*). Where the city distinguishes *Frauen*
  from *Mädchen* without saying where one ends, neither member carries an age.
  `AdultsOnly.min_age = 18` predates this rule and is unsourced — tracked, not endorsed.
- **Deny only what the source lets you deny.** `GirlsOnly` denies a non-female person — that
  is the restriction the page states — and answers *not determinable* for a female one,
  because the cutoff is unpublished. `GenderDiverse` **never hard-denies above its stated
  age**: being trans is not a value of `Person.gender`, so a trans woman's gender is
  *female*, and deciding the session from that enum would wrongly exclude her. The only
  checkable fact there is the published minimum age. `AccompaniedChildren` is always not
  determinable — whether someone is accompanied is unknowable, and inventing an adult
  threshold would repeat the `AdultsOnly` mistake.
- **Classifying must not destroy the source.** The verbatim cell a rule was derived from
  lives on `ScheduleRule.source_text`, so the German prose, the per-session depth
  (`Tiefe 135 cm`) and any footnote marker survive classification.

The union is the *derived* view; `source_text` is the *fact*. Where they disagree, the
source wins and the classifier is wrong.

---
type: concept
created: 2026-08-14
links: ["[[day-tail-time-axis]]", "[[2026-08-13-mobile-daytail-time-axis-plan]]", "[[mobile-daytail-time-axis]]"]
---

# The phone card's button holds non-phrasing content — what that actually costs

`.plist__btn` is a native `<button>` containing `div.plist__head` (which holds `h3.plist__name` and
two `p`s), `p.plist__meta`, and — since [[2026-08-13-mobile-daytail-time-axis-plan]] — `div.plist__plot`
with the hour strip and the tail canvas. A `<button>` may contain **phrasing content only**, so all
of that is invalid HTML.

**Two things are commonly said about this, and one of them is wrong.**

Wrong: "it is fine because we build the tree with `createElement`/`appendChild` rather than parsing
markup." The content model applies however the nodes are created; the DOM API simply does not
enforce it. What construction-by-API genuinely avoids is *parser fixup* — a literal `<div>` inside
`<button>` in markup is hoisted **out** of the button by the parser, which would silently destroy
the tap target. So the distinction is real, but it buys structural survival, not conformance.

Right, and the part worth acting on: **a button's descendants are exposed to accessibility APIs as
presentational.** `h3.plist__name` is therefore not a navigable heading. A screen-reader user cannot
move pool-to-pool by heading through a ~58-row list; they get 58 buttons whose accessible name is the
flattened text of everything inside. That is the actual cost, and it predates the day-tail work —
the `h3` has been inside the button since the card was built.

**Why it is not fixed in passing.** Conforming means changing what the clickable element *is*, and
every option has a real cost:

- **`div[role="button"]`** — the heading can stay a heading, but keyboard semantics
  (Enter/Space activation, focus order) become hand-rolled, and `--focus-ring-inset` (added because
  `.plist__card` clips) would need re-deriving against a non-button box.
- **Stretched-link pattern** — a small real `<button>` or `<a>` inside the card, absolutely
  positioned to cover it, with the heading outside the control. Keeps native semantics, but the
  card's whole surface becomes a click target owned by an element that is not its content, and text
  selection inside the card stops working.
- **Demote the `h3` to a `span`** — makes the markup conform by deleting the very semantics that are
  being lost. Conformance without benefit.

None of these is a tidy-up; each changes the card's interaction model, and the first two touch the
focus-ring work the day-tail plan just landed. Recorded here so the trade-off is decided
deliberately, rather than rediscovered by a linter and patched in the cheapest direction.

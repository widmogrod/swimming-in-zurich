"""Pure domain: models, schedule resolution, eligibility, and the query surface.

This layer has no I/O and no external dependencies beyond the standard library. It is the
part that must be *correct*: given a curated dataset it answers "where can I swim?" for any
concrete date, including future dates governed by school-term/holiday calendars and
maintenance closures.
"""

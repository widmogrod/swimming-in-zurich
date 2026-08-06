// locales/de.ts — German (Swiss usage).
//
// SWISS ORTHOGRAPHY: never ß, always ss ("Schliessung", "Strasse", "grösste"). Switzerland
// abolished the eszett; using it would read as foreign in the one locale whose speakers
// are the app's largest audience. `datefmt` formats de as **de-CH** for the same reason.
//
// Shape is enforced by `CatalogFor<'de'>`: a missing key, or a bare string where English
// has a plural, is a compile error. German needs only one/other.

import type { CatalogFor } from "../i18n.js";

export const de = {
  "common.today": "Heute",
  "board.hoursNotListed": "Öffnungszeiten nicht angegeben",
  "board.poolCount": {
    one: "{count} Bad",
    other: "{count} Bäder",
  },
  "basin.laneCount": {
    one: "{count} Bahn",
    other: "{count} Bahnen",
  },

  "insight.day.pools": {
    one: "{count} Bad mit erfassten Zeiten in der Nähe",
    other: "{count} Bäder mit erfassten Zeiten in der Nähe",
  },
  "insight.day.none":
    "Keine Bäder mit erfassten Zeiten für diesen Tag in der Nähe",
  "insight.bestWindow":
    "bestes öffentliches Fenster {public}/{total} im {facility} {start}–{end}",
  "insight.noSplit": "Bahnenaufteilung noch nicht veröffentlicht",
  "insight.noSplit.label": "Bahnenaufteilung nicht veröffentlicht",
  "insight.coverage":
    "{closed} geschlossen, {unlisted} ohne Zeitangabe in der Nähe",
  "insight.pool.reliable":
    "Verlässliche öffentliche Bahnen im {facility}: bis zu {public} von {total} gegen {start}",
  "insight.pool.openDays": {
    one: "{count} von 7 Tagen diese Woche offen",
    other: "{count} von 7 Tagen diese Woche offen",
  },
  "insight.pool.none":
    "{facility}: diese Woche keine öffentlichen Zeiten gefunden",
  "insight.pool.thisPool": "dieses Bad",

  "state.closed.title": "Geschlossen",
  "state.closed.body": "Geschlossen — {detail}",
  "state.closed.bodyNoReason": "Zurzeit geschlossen.",
  "state.unlisted.title": "Öffnungszeiten noch nicht angegeben",
  "state.unlisted.body":
    "Wir haben den Zeitplan dieses Bads noch nicht — es kann durchaus offen sein. Das ist nicht dasselbe wie geschlossen.",
  "state.none.title": "Keine Bäder in der Nähe",
  "state.none.body":
    "Hier passt nichts — versuchen Sie einen grösseren Umkreis oder einen anderen Tag. Das ist nicht dasselbe wie geschlossen.",
  "state.unlisted.summary": {
    one: "{count} weiteres Bad in der Nähe — Öffnungszeiten nicht angegeben",
    other: "{count} weitere Bäder in der Nähe — Öffnungszeiten nicht angegeben",
  },

  "legend.label": "Legende",
  "legend.group.sessionType": "Art des Angebots",
  "legend.group.availability": "Verfügbarkeit",
  "legend.group.forYou": "Für Sie",
  "legend.honestyNote":
    "Die Banddicke ist die tatsächliche heutige Aufteilung der öffentlichen Bahnen — nicht die Auslastung, für die es noch keine Quelle gibt.",
  "access.public": "Öffentliches Schwimmen",
  "access.lane": "Bahnenschwimmen",
  "access.family": "Familienzeit",
  "access.women": "Nur Frauen",
  "access.seniors": "Nur Seniorinnen und Senioren",
  "access.adults": "Nur Erwachsene",
  "access.school": "Für Schulen reserviert",
  "access.club": "Für Vereine reserviert",
  "access.girls": "Nur für Mädchen",
  "access.genderDiverse": "Trans und nicht-binäre Personen",
  "access.accompanied": "Kinder nur mit Erwachsenen",
  "legend.state.open": "Offen (öffentliche Bahnen)",
  "legend.state.closed": "Geschlossen — mit Begründung",
  "legend.state.unknown": "Öffnungszeiten noch nicht angegeben",

  "status.closed": "Geschlossen",
  "status.closed_reason": "Geschlossen · {reason}",
  "status.uncurated": "Öffnungszeiten nicht angegeben",
  "status.awaiting_scrape": "Öffnungszeiten noch nicht veröffentlicht",
  "status.no_source": "Öffnungszeiten nicht angegeben",

  // seasonal-hours S4: per-SESSION fair-weather marker; {spans} are the conditional clock spans.
  "session.fairWeather": "Nur bei schönem Wetter · {spans}",

  "closure.seasonal_break": "Sommerpause",
  "closure.seasonal_break_maintenance": "Sommerpause / Revision",
  "closure.maintenance": "Revision",
  "closure.operational_break": "Betriebsferien",
  "closure.christmas_eve": "Heiligabend",
  "closure.public_holiday": "Feiertag",
  "closure.public_holiday_named": "{holiday}",
  "closure.no_sessions": "Keine Zeiten angesetzt",
  // Season-NEUTRAL: "Ausserhalb der Saison", never "Winterpause" — the code is derived from
  // the pool's own window and a Hallenbad's off-season is the summer.
  "closure.out_of_season": "Ausserhalb der Saison",
  "closure.special": "Geschlossen",
  "closure.unmapped": "{text}",

  // German is the SOURCE language of this data, so these are simply the curated names.
  "holiday.new_year": "Neujahr",
  "holiday.berchtoldstag": "Berchtoldstag",
  "holiday.good_friday": "Karfreitag",
  "holiday.easter_monday": "Ostermontag",
  "holiday.labour_day": "Tag der Arbeit",
  "holiday.ascension": "Auffahrt",
  "holiday.whit_monday": "Pfingstmontag",
  "holiday.national_day": "Bundesfeier",
  "holiday.christmas": "Weihnachten",
  "holiday.st_stephens": "Stephanstag",
  "holiday.unknown": "{holiday}",

  "elig.in": "Sie können hinein",
  "elig.chk": "Beim Bad nachfragen",
  "elig.no": "Nicht für Sie",
  "elig.chk.short": "Nachfragen",

  "pill.open": "Offen",
  "pill.opensLater": "Öffnet später",
  "pill.closed": "Geschlossen",
  "pill.unknown": "Öffnungszeiten nicht angegeben",

  "badge.teachingPool": "Lehrschwimmbecken",
  "badge.metres": "{length} m",
  "age.minutes": "{count} Min.",
  "age.hours": "{count} Std.",
  "age.days": {
    one: "{count} Tag",
    other: "{count} Tage",
  },
  "badge.poolAria": "{length}-Meter-Becken, {lanes}",

  "sources.label": "Quellen",
  "sources.official": "Offizielle Seite",
  "sources.lanePlan": "Belegungsplan",
  "sources.prices": "Preise",
  "sources.pdf": "PDF",
  "sources.pdfLabel": "{label} PDF",
  "sources.chipAria": "{name} — öffnet {host} in einem neuen Tab",

  "combo.noMatches": "Keine Treffer",
  "combo.noPoolsMatch": "Keine Bäder gefunden",
  "place.useMyLocation": "Meinen Standort verwenden",
  "place.myLocation": "Mein Standort",

  "date.selectedDay": "Gewählter Tag",
  "date.previousDay": "Vorheriger Tag",
  "date.nextDay": "Nächster Tag",
  "date.selectedWeek": "Gewählte Woche",
  "date.previousWeek": "Vorherige Woche",
  "date.nextWeek": "Nächste Woche",
  "date.weekOf": "Woche vom {date}",

  "app.title": "Schwimmen in Zürich",
  "header.language": "Sprache",
  "header.copyLink": "Link kopieren",
  "header.copied": "Kopiert",
  "header.copyAria": "Einen teilbaren Link zu dieser Ansicht kopieren",
  "header.themeAria": "Darstellung: {theme} (zum Ändern klicken)",
  "theme.auto": "Automatisch",
  "theme.light": "Hell",
  "theme.dark": "Dunkel",

  "gantt.lane": "Bahn {lane}",
  "gantt.public": "Öffentlich",
  "gantt.reserved": "Reserviert",
  "gantt.readout": "{hhmm} · {public} von {total} Bahnen öffentlich",

  "toolbar.label": "Suchfilter",
  "toolbar.view": "Ansicht",
  "toolbar.viewMode": "Ansichtsmodus",
  "toolbar.mode.day": "Tag",
  "toolbar.mode.pool": "Bad",
  "toolbar.near": "Nähe",
  "toolbar.wherefrom": "Von wo?",
  "toolbar.gender": "Geschlecht",
  "toolbar.gender.any": "Alle",
  "toolbar.gender.female": "Weiblich",
  "toolbar.gender.male": "Männlich",
  "toolbar.gender.diverse": "Divers",
  "toolbar.age": "Alter",
  "toolbar.age.any": "Jedes Alter",
  "toolbar.age.child": "Kind",
  "toolbar.age.teen": "Jugendlich",
  "toolbar.age.adult": "Erwachsen",
  "toolbar.age.senior": "Senior",
  "toolbar.lapOnly": "Nur Bahnen",
  "toolbar.busyness": "Auslastung",
  "toolbar.busynessReason":
    "Für die Auslastung gibt es noch keine Datenquelle — nicht verfügbar.",
  "toolbar.searchPool": "Bad suchen…",
  "toolbar.pool": "Bad",

  "detail.fact.today": "Heute",
  "detail.fact.basin": "Becken",
  "detail.fact.distance": "Entfernung",
  "detail.fact.price": "Preis",
  "detail.fact.water": "Wasser",
  "detail.fact.liveWater": "Wasser aktuell",
  "detail.fact.eligibility": "Zutritt",
  "detail.fact.busyness": "Auslastung",
  "detail.fact.freshness": "Stand",

  "price.adult": "Erwachsene {amount}",
  "price.youth": "Jugendliche {amount}",
  "price.child": "Kinder {amount}",
  "price.senior": "Senioren {amount}",

  "detail.notListed": "Nicht angegeben",
  "detail.notShown": "Nicht angezeigt",
  "detail.notDated": "Ohne Datum",
  "detail.notAvailable": "Nicht verfügbar",
  "detail.notAvailableYet": "Noch nicht verfügbar",
  "detail.notYetMeasured": "Noch nicht gemessen",
  "live.not_configured": "Nicht eingerichtet",
  "live.provider_error": "Quelle nicht erreichbar",
  "live.no_key": "Nicht verfügbar",
  "detail.liveOpen": "offen",
  "detail.liveClosed": "geschlossen",
  "board.nearestFirst": "Nächste zuerst",
  "detail.waterNotPublished": "Wassertemperatur nicht veröffentlicht",
  "detail.tempMeasured": "gemessen",
  "detail.liveMeasuredAgo": "vor {age} gemessen",
  "detail.closedNote": "Geschlossen — {reason}. {note}",
  "detail.tempNominal": "nominal (Auslegung)",
  "detail.checked": "Geprüft am {date}",
  "detail.weekButton": "Woche dieses Bads ansehen →",
  "detail.pool": "Bad",
  "detail.openLaneSplit": "Offen · Bahnenaufteilung nicht veröffentlicht",
  "detail.noPublicLanes": "Heute keine öffentlichen Bahnen",
  "detail.openRange": "Offen · {from}–{to}",
  "detail.closedReason": "Geschlossen · {reason}",
  "detail.hoursUnknown":
    "Öffnungszeiten nicht angegeben — kann durchaus offen sein",
  "detail.headline": "von {total} Bahnen öffentlich · {hhmm}",
  "detail.peakNote": "Spitze {peak} von {total}",
  "detail.headlineAria":
    "{public} von {total} Bahnen öffentlich um {hhmm} (Spitze {peak})",
  "detail.note.lanesUnknown":
    "Für dieses Bad ist noch kein Belegungsplan veröffentlicht — die Zeiten sind erfasst, die Aufteilung in öffentliche und reservierte Bahnen aber nicht.",
  "detail.note.closed":
    "Dieses Bad ist an diesem Tag aus einem angegebenen Grund geschlossen — das wird nicht mit Bädern vermischt, zu denen uns schlicht Daten fehlen.",
  "detail.note.uncurated":
    "Wir kennen den Standort dieses Bads, haben aber noch keinen Zeitplan. Unbekannt ist nicht dasselbe wie geschlossen — es kann durchaus offen sein.",
  "detail.emptyPanel":
    "Klicken Sie auf ein Bad, um Zeiten, Preis und Belegungsplan zu sehen.",

  "prov.scraped": "Offizieller Zeitplan — von der Seite des Bads übernommen",
  "prov.awaiting": "Noch kein Zeitplan veröffentlicht",
  "prov.noSource": "Keine Zeitplanquelle für dieses Bad",
  "prov.lastChecked": " · zuletzt geprüft am {date}",

  "mobile.tier.now": "Jetzt schwimmen",
  "mobile.tier.soon": "Später heute",
  "mobile.tier.unknown": "Keine Zeiten hinterlegt",
  "mobile.tier.closed": "Geschlossen",

  "mobile.verdict.openNow": "Jetzt offen",
  "mobile.verdict.partlyReserved": "Teilweise reserviert",
  "mobile.verdict.notYoursUntil": "Erst ab {hhmm} für dich",
  "mobile.verdict.opensAt": "Öffnet {hhmm}",
  "mobile.verdict.doneForToday": "Heute vorbei",
  "mobile.verdict.closedAllDay": "Ganztags geschlossen",
  "mobile.verdict.hoursUnknown": "Keine Zeiten hinterlegt",
  "mobile.verdict.untilTime": "bis {hhmm}",
  "mobile.lanesUntil": "{public} von {total} Bahnen öffentlich bis {hhmm}",

  "mobile.openToYou": {
    one: "{count} jetzt für dich offen",
    other: "{count} jetzt für dich offen",
  },
  "mobile.openToYouOn": {
    one: "{count} offen für dich am {day}",
    other: "{count} offen für dich am {day}",
  },
  "mobile.filters": "Filter",
  "mobile.today": "Heute",
  "mobile.lanePlan": "Bahnenplan",
} as const satisfies CatalogFor<"de">;

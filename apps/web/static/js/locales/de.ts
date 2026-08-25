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
  // --- Der Bahnen-Stapel (lane-stack-board S4) -------------------------------------
  "legend.group.laneStack": "Bahnen-Stapel",
  "legend.lane.public": "Bahn öffentlich zugänglich",
  "legend.lane.reserved": "Bahn reserviert (Name, wo Platz ist)",
  "legend.lane.best": "Die meisten öffentlichen Bahnen frei",
  "legend.lane.unpublished": "Bahneneinteilung nicht veröffentlicht",

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
  "board.noSessionsGroup": "Heute keine Zeiten publiziert",
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
  // --- Die native iOS-App (native-ios-app S4) ---------------------------------------

  // Tageszustände: vier der fünf sagen aus, dass wir die Zeiten NICHT kennen — keiner
  // davon darf als "geschlossen" formuliert sein.
  "state.openUnscheduled": "Offen, Zeiten nicht angegeben",
  "state.beyondHorizon": "Ausserhalb des veröffentlichten Zeitraums",
  "state.beyondHorizon.body":
    "Wir liefern Antworten bis {date}. Das heisst nicht, dass die Bäder geschlossen sind — wir haben diesen Tag schlicht noch nicht aufgelöst.",
  "state.notStated": "Zustand nicht angegeben",
  "state.unrecognised": "{status}",
  "state.closed.outOfSeason": "Geschlossen — ausserhalb der Saison",
  "state.closed.noSessions": "Geschlossen — keine Zeiten angesetzt",
  "state.closed.unmapped": "Geschlossen — „{text}“",
  "state.closed.unclassified": "Geschlossen — Grund nicht zugeordnet",
  "state.closed.other": "Geschlossen — {code}",
  "state.closed.unstated": "Geschlossen — Grund nicht angegeben",

  "tier.scheduled": "An diesem Tag offen",
  "verdict.notOpenToYou": "Nicht für Sie offen",
  "verdict.hasSessions": "Hat Zeiten",
  "headline.poolsWithSessions": {
    one: "{count} Bad mit Zeiten",
    other: "{count} Bäder mit Zeiten",
  },
  "row.moreToday": "+{count} weitere heute",
  "row.moreThatDay": "+{count} weitere an dem Tag",

  "banner.calendarCoverage.title": "Feiertagskalender unvollständig",
  "banner.holidayHoursUnverified.title": "Feiertagszeiten unbestätigt",
  "banner.generic.title": "Bitte beachten",
  "warning.calendar_coverage":
    "Für {year} liegen keine Kalenderdaten vor; feiertagsabhängige Zeitpläne können ungenau sein.",
  "warning.holiday_hours_unverified":
    "{date} ist ein Feiertag, und diese Bäder veröffentlichen keine Feiertagszeiten; angezeigt sind ihre üblichen Wochentagszeiten, unbestätigt: {pools}",
  "warning.unknown": "{code}",

  "access.public.desc":
    "Öffentliches Schwimmen — während dieser Zeiten hat jede und jeder Zutritt.",
  "access.lane.desc":
    "Bahnenschwimmen — öffentlich, in Bahnen eingeteilt für Längen und Training.",
  "access.family.desc":
    "Familien- und Kinderzeit — öffentlich, auf Familien und Kinder ausgerichtet.",
  "access.women.desc": "Frauenschwimmen (Frauenbad) — nur für Frauen.",
  "access.seniors.desc": "Seniorenzeit — reserviert für Gäste ab 60 Jahren.",
  "access.school.desc":
    "Für Schulklassen reserviert — nicht öffentlich zugänglich.",
  "access.club.desc":
    "Für einen Verein reserviert — nicht öffentlich zugänglich.",
  "access.adults.desc":
    "Öffentliches Fenster nur für Erwachsene — reserviert für Gäste ab 18 Jahren (typisch für Abendschwimmen in Schulbädern).",
  "access.girls.desc":
    "Nur für Mädchen — das Bad nennt keine Altersgrenze, bitte dort nachfragen.",
  "access.genderDiverse.desc":
    "Angebot für trans und nicht-binäre Personen ab 16 Jahren.",
  "access.accompanied.desc":
    "Für Kinder nur in Begleitung Erwachsener (für Kinder nur mit Erwachsenen).",
  // Nie "öffentliches Schwimmen" für eine unbekannte Art — das wäre eine Einladung
  // statt eines Hinweises zum Nachfragen.
  "access.unknown": "Angebot — beim Bad nachfragen",

  "poolKind.indoor": "Hallenbad",
  "poolKind.outdoor": "Freibad",
  "poolKind.lake": "Seebad",
  "poolKind.river": "Flussbad",
  "poolKind.thermal": "Thermalbad",
  "poolKind.school": "Schulschwimmanlage",
  "poolKind.paddling": "Planschbecken",
  "poolKind.unknown": "{kind}",

  // --- Das Bad-Blatt ----------------------------------------------------------------
  "detail.section.where": "Standort",
  "detail.section.admission": "Eintritt",
  "detail.section.season": "Saison",
  "detail.section.basins": "Becken",
  "detail.section.features": "Angebote",
  "detail.section.lockers": "Garderoben",
  "detail.section.rentals": "Vermietung",
  "detail.section.lanes": "Belegungspläne",
  "detail.section.provenance": "Woher diese Angaben stammen",

  "detail.fact.address": "Adresse",
  "detail.fact.phone": "Telefon",
  "detail.fact.website": "Website",
  "detail.fact.about": "Über das Bad",
  "detail.fact.schedule": "Zeitplan",
  "detail.fact.entry": "Eintritt",
  "detail.fact.yourRate": "Ihr Tarif",
  "detail.fact.pricesRead": "Preise gelesen",
  "detail.fact.tariffPage": "Tarifseite",
  "detail.fact.lastAdmission": "Letzter Einlass",
  "detail.fact.season": "Badesaison",

  "freshness.scraped": "Vom Bad veröffentlicht",
  "freshness.awaiting": "Noch nicht veröffentlicht",
  "freshness.noSource": "Kein Zeitplan zum Auslesen",
  "freshness.unknown": "Unbekannter Zustand: {state}",
  "freshness.awaiting.caveat":
    "Dieses Bad hat eine Zeitplanseite, sie wurde aber noch nicht in diese App übernommen.",
  "freshness.noSource.caveat":
    "Dieses Bad veröffentlicht keinen eigenen Zeitplan. Das ist nicht dasselbe wie geschlossen.",
  "freshness.unknown.caveat":
    "Diese App kennt diesen Zustand nicht; bitte beim Bad nachfragen.",

  "priceCategory.adult": "Erwachsene",
  "priceCategory.youth": "Jugendliche",
  "priceCategory.child": "Kinder",
  "priceCategory.senior": "Senioren",
  "priceCategory.unknown": "{category}",
  "price.minAgeCaveat": "Veröffentlicht für Personen ab {minAge} Jahren.",
  "price.staleCaveat":
    "Die Preise stammen von der Seite des Bads und können sich ohne Ankündigung ändern.",

  "admission.free": "Gratis",
  "admission.tariff": "Kostenpflichtig — Tarife unten",
  // NICHT "gratis": ein nicht angegebener Eintritt ist unbekannt.
  "admission.unknown": "Nicht angegeben — beim Bad nachfragen",
  "detail.lastAdmission.value": "{duration} vor Schliessung",

  "season.range": "{from} bis {to}",
  "season.rangeWithDays": "{startDay} {from} bis {endDay} {to}",
  "season.fairWeatherCaveat":
    "Angegeben für schönes Wetter; bei schlechtem Wetter kann das Bad geschlossen bleiben.",

  "basin.fact.size": "Grösse",
  "basin.fact.lanes": "Bahnen",
  "basin.fact.water": "Wasser",
  "basin.fact.diving": "Sprunganlage",
  "basin.fact.lanePlan": "Belegungsplan",
  "basin.size.lengthByWidth": "{length} × {width}",
  "basin.size.length": "{length}",
  "basin.size.width": "{width} breit",
  "basin.tempNominalCaveat": "Die Angabe des Bads, keine Messung.",
  "basin.parsedProseCaveat":
    "Aus dem Fliesstext des Bads gelesen, daher möglicherweise ungenau.",
  "basinKind.swimmer": "Schwimmerbecken",
  "basinKind.non_swimmer": "Nichtschwimmerbecken",
  "basinKind.diving": "Sprungbecken",
  "basinKind.learner": "Lehrschwimmbecken",
  "basinKind.paddling": "Planschbecken",
  "basinKind.multi_purpose": "Mehrzweckbecken",
  "basinKind.thermal": "Thermalbecken",
  "basinKind.outdoor": "Aussenbecken",
  "basinKind.unknown": "{kind}",

  "feature.fact.surcharge": "Zuschlag",
  "feature.fact.temperature": "Temperatur",
  "feature.fact.hours": "Zeiten an diesem Tag",
  "feature.hoursNotListed": "Zeiten für diesen Tag nicht angegeben",
  "feature.closed": "Geschlossen — {reason}",
  // Kleingeschrieben: diese Teilsätze werden INNERHALB von `feature.closed` gelesen.
  "closureClause.out_of_season": "ausserhalb der Saison",
  "closureClause.no_sessions": "für diesen Tag keine Zeiten veröffentlicht",
  "closureClause.closure": "das Bad meldet eine Schliessung",
  "closureClause.unknown": "{reason}",
  "featureKind.sauna": "Sauna",
  "featureKind.gastronomy": "Restaurant oder Kiosk",
  "featureKind.sunbathing": "Liegewiese",
  "featureKind.playground": "Spielplatz",
  "featureKind.slide": "Wasserrutsche",
  "featureKind.wellness": "Wellnessbereich",
  "featureKind.sport": "Sportanlage",
  "featureKind.unknown": "{kind}",

  "lockerKind.wardrobe": "Garderobenkästchen",
  "lockerKind.valuables": "Wertfach",
  "lockerKind.cabin": "Umkleidekabine",
  "lockerKind.unknown": "{kind}",
  "rentalKind.towel": "Badetuch",
  "rentalKind.locker": "Kästchen",
  "rentalKind.deck_chair": "Liegestuhl",
  "rentalKind.swim_aid": "Schwimmhilfe",
  "rentalKind.unknown": "{kind}",
  "fee.free": "Gratis",
  "fee.unstated": "Preis nicht angegeben",
  "fee.amount": "{amount}",
  "fee.perPeriod": "pro {period}",
  "fee.deposit": "Depot {amount}",

  "panel.bestWindow": {
    one: "{start}–{end}, {count} Bahn",
    other: "{start}–{end}, {count} Bahnen",
  },
  "panel.clubSlot.oneLane": "{start}–{end}, Bahn {lanes}",
  "panel.clubSlot.manyLanes": "{start}–{end}, Bahnen {lanes}",
  "prov.fact.readFrom": "Gelesen von",
  "prov.fact.accurateAsOf": "Stand",
  "prov.fact.curation": "Prüfung",
  "prov.curated.yes": "Von Hand geprüft",
  "prov.curated.no": "Direkt von der Seite des Bads übernommen",

  // --- Belegungspläne ---------------------------------------------------------------
  "lane.incompleteCaveat":
    "Einzelne Bahnen liessen sich aus dem Plan des Bads nicht lesen, daher ist die Angabe unvollständig.",
  // Null öffentliche Bahnen ist NICHT "0 von 8 offen" — jede Variante ist ein ganzer Satz.
  "lane.nonePublic": "keine Bahnen öffentlich zugänglich",
  "lane.nonePublic.partial":
    "keine Bahnen öffentlich zugänglich — einzelne Bahnen nicht lesbar",
  "lane.publicOfTotal": {
    one: "{public} von {count} Bahn öffentlich",
    other: "{public} von {count} Bahnen öffentlich",
  },
  "lane.publicOfTotal.partial": {
    one: "{public} von {count} Bahn öffentlich — einzelne Bahnen nicht lesbar",
    other:
      "{public} von {count} Bahnen öffentlich — einzelne Bahnen nicht lesbar",
  },
  "lane.openToPublic": "öffentlich zugänglich",
  "lane.spoken": "Bahn {lane}, {start} bis {end}, {holder}",

  // --- VoiceOver über dem Bänder-Canvas ---------------------------------------------
  "a11y.blockLabel": "{start} bis {end}, {access}",
  "a11y.fact.publicLanes": "Öffentlich zugängliche Bahnen",
  "a11y.value.ofTotal": "{public} von {total}",
  "a11y.fact.laneData": "Bahnendaten",
  "a11y.value.laneDataIncomplete": "unvollständig für dieses Becken",
  "a11y.fact.lanes": "Bahnen",
  "a11y.fact.reservedBy": "Reserviert für",
  "a11y.value.ownerAndOthers": "{owner} und weitere",
  "a11y.fact.laneSplit": "Bahnenaufteilung",
  "a11y.value.laneSplitUnpublished": "für dieses Bad nicht veröffentlicht",
  "a11y.selected": "Ausgewählt",

  // --- Rahmen der App ---------------------------------------------------------------
  "nav.map": "Karte",
  "nav.list": "Liste",
  "action.directions": "Route",
  "action.call": "Anrufen",
  "action.openInMaps": "In Karten öffnen",
  "nav.allPools": "Alle Bäder",
  "nav.accessTypes": "Was die Angaben bedeuten",
  "nav.browse": "Stöbern",
  "nav.findAPool": "Bad finden",
  "accessTypes.title": "Arten von Angeboten",
  "accessTypes.footer":
    "Die Regeln des einzelnen Angebots gelten immer: Was ein Bad für eine bestimmte Stunde veröffentlicht, zeigt diese App — und das sind die Kategorien, in die sie es einordnet.",
  "browser.noMatch.body": "Anderen Namen oder eine andere Art versuchen.",
  "browser.filterByKind": "Nach Art filtern",
  "browser.kind": "Art",
  "browser.allKinds": "Alle Arten",
  "gantt.title": "Bahnen, Stunde für Stunde",
  "error.store.title": "Baddaten nicht lesbar",
  "error.store.body":
    "Die mitgelieferten Baddaten liessen sich nicht öffnen, daher gibt es nichts anzuzeigen. Eine Neuinstallation stellt sie wieder her.",
  "state.none.body.phone":
    "Grösseren Umkreis, anderen Tag oder weniger Filter versuchen. Das ist nicht dasselbe wie geschlossen.",
  "meta.dataFrom": "Daten von",
  "meta.answersThrough": "Antworten bis",
  "meta.offlineNote":
    "Funktioniert offline. Alles hier wurde vor der Auslieferung der App aufgelöst.",
  "action.favourite": "Merken",
  "action.unfavourite": "Nicht mehr merken",
  "action.showLanePlan": "Belegungsplan anzeigen",
  "action.hideLanePlan": "Belegungsplan ausblenden",
  "action.done": "Fertig",
  "session.fairWeather.badge": "Nur bei schönem Wetter",
  "filter.none": "Keine Filter",
  "filter.section.who": "Wer",
  "filter.section.where": "Wo",
  "filter.section.what": "Was",
  "filter.eligibleOnly": "Nur für mich offen",
  "filter.eligibleOnly.toggle": "Nur Angebote, die für mich offen sind",
  "filter.favourites": "Gemerkt",
  "filter.favouritesOnly.toggle": "Nur Gemerktes",
  "filter.measureFrom": "Entfernung ab",
  "filter.within": "Umkreis",
  "filter.anyDistance": "Beliebig weit",
  "filter.poolKinds": "Arten von Bädern",
  "filter.allKinds": "Alle",
  "place.anywhere": "Überall",
  "place.searchPrompt": "Orte suchen",
  "place.hb": "Zürich HB (Hauptbahnhof)",
} as const satisfies CatalogFor<"de">;

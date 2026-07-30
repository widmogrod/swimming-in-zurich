// locales/pl.ts — Polish.
//
// ⚠️ NOT YET NATIVE-REVIEWED. This catalogue is a first pass and MUST be signed off by a
// native speaker before `pl` is offered to users — see the plan's "Polish cannot be
// broken" §7. It is not registered in the locale switcher until then.
//
// PLURALS ARE COMPILE-ENFORCED. `CatalogFor<'pl'>` requires all four CLDR categories on
// every plural entry; omitting `many` is a `tsc` error, not a silent fallback that reads
// as broken grammar. The categories, for reference:
//
//   one   — 1                                    "1 basen"
//   few   — 2-4, 22-24, 32-34 …                  "22 baseny"   (NOT many!)
//   many  — 0, 5-21, 25-31 …                     "5 basenów", "0 basenów"
//   other — fractions only                       "1,5 basenu"  (genitive singular)
//
// Note `other` is NOT a general fallback: it is the FRACTION form. Writing the plural
// there would produce "1,5 baseny", which is wrong.
//
// GENDER: user-facing copy is phrased impersonally on purpose. Polish adjectives and
// past-tense verbs agree with the subject's gender, and the app's gender axis includes
// `diverse`, for which Polish has no settled form. "You're in" is "Możesz wejść" ("one
// may enter"), never a gendered construction.

import type { CatalogFor } from "../i18n.js";

export const pl = {
  "common.today": "Dzisiaj",
  "board.hoursNotListed": "Godziny nieopublikowane",
  "board.poolCount": {
    one: "{count} basen",
    few: "{count} baseny",
    many: "{count} basenów",
    other: "{count} basenu",
  },
  "basin.laneCount": {
    one: "{count} tor",
    few: "{count} tory",
    many: "{count} torów",
    other: "{count} toru",
  },

  "insight.day.pools": {
    one: "{count} basen z opracowanymi godzinami w pobliżu",
    few: "{count} baseny z opracowanymi godzinami w pobliżu",
    many: "{count} basenów z opracowanymi godzinami w pobliżu",
    other: "{count} basenu z opracowanymi godzinami w pobliżu",
  },
  "insight.day.none":
    "Brak basenów z opracowanymi godzinami na ten dzień w pobliżu",
  "insight.bestWindow":
    "najlepsze okno publiczne {public}/{total} — {facility}, {start}–{end}",
  "insight.noSplit": "podział torów jeszcze nieopublikowany",
  "insight.noSplit.label": "Podział torów nieopublikowany",
  "insight.coverage": "{closed} zamkniętych, {unlisted} bez godzin w pobliżu",
  "insight.pool.reliable":
    "Pewne tory publiczne — {facility}: do {public} z {total} około {start}",
  "insight.pool.openDays": {
    one: "otwarte {count} z 7 dni w tym tygodniu",
    few: "otwarte {count} z 7 dni w tym tygodniu",
    many: "otwarte {count} z 7 dni w tym tygodniu",
    other: "otwarte {count} z 7 dni w tym tygodniu",
  },
  "insight.pool.none": "{facility}: brak zajęć publicznych w tym tygodniu",
  "insight.pool.thisPool": "ten basen",

  "state.closed.title": "Zamknięte",
  "state.closed.body": "Zamknięte — {detail}",
  "state.closed.bodyNoReason": "Obecnie zamknięte.",
  "state.unlisted.title": "Godziny jeszcze nieopublikowane",
  "state.unlisted.body":
    "Nie mamy jeszcze harmonogramu tego basenu — może być otwarty. To nie to samo co zamknięty.",
  "state.none.title": "Brak basenów w pobliżu",
  "state.none.body":
    "Nic tu nie pasuje — spróbuj większego obszaru albo innego dnia. To nie to samo co zamknięte.",
  "state.unlisted.summary": {
    one: "jeszcze {count} basen w pobliżu — godziny nieopublikowane",
    few: "jeszcze {count} baseny w pobliżu — godziny nieopublikowane",
    many: "jeszcze {count} basenów w pobliżu — godziny nieopublikowane",
    other: "jeszcze {count} basenu w pobliżu — godziny nieopublikowane",
  },

  "legend.label": "Legenda",
  "legend.group.sessionType": "Rodzaj zajęć",
  "legend.group.availability": "Dostępność",
  "legend.group.forYou": "Dla Ciebie",
  "legend.honestyNote":
    "Grubość wstęgi to rzeczywisty dzisiejszy podział torów publicznych — nie obłożenie, dla którego nie ma jeszcze źródła.",
  "access.public": "Pływanie publiczne",
  "access.lane": "Pływanie na torach",
  "access.family": "Czas dla rodzin",
  "access.women": "Tylko dla kobiet",
  "access.seniors": "Tylko dla seniorów",
  "access.adults": "Tylko dla dorosłych",
  "access.school": "Zarezerwowane dla szkół",
  "access.club": "Zarezerwowane dla klubu",
  "legend.state.open": "Otwarte (tory publiczne)",
  "legend.state.closed": "Zamknięte — z podaniem powodu",
  "legend.state.unknown": "Godziny jeszcze nieopublikowane",

  "status.closed": "Zamknięte",
  "status.closed_reason": "Zamknięte · {reason}",
  "status.uncurated": "Godziny nieopublikowane",
  "status.awaiting_scrape": "Godziny jeszcze nieopublikowane",
  "status.no_source": "Godziny nieopublikowane",

  "closure.seasonal_break": "Przerwa letnia",
  "closure.seasonal_break_maintenance": "Przerwa letnia / remont",
  "closure.maintenance": "Remont",
  "closure.operational_break": "Przerwa zakładowa",
  "closure.christmas_eve": "Wigilia",
  "closure.public_holiday": "Dzień świąteczny",
  "closure.public_holiday_named": "{holiday}",
  "closure.no_sessions": "Brak zaplanowanych zajęć",
  "closure.special": "Zamknięte",
  "closure.unmapped": "{text}",

  "holiday.new_year": "Nowy Rok",
  // Swiss/Liechtenstein-only: no Polish equivalent exists, so the German name is kept and
  // GLOSSED rather than invented. See the plan's holiday tiering.
  "holiday.berchtoldstag": "Berchtoldstag (2 stycznia, święto w Szwajcarii)",
  "holiday.good_friday": "Wielki Piątek",
  "holiday.easter_monday": "Poniedziałek Wielkanocny",
  "holiday.labour_day": "Święto Pracy",
  "holiday.ascension": "Wniebowstąpienie Pańskie",
  "holiday.whit_monday": "Poniedziałek Zielonych Świątek",
  "holiday.national_day": "Święto Narodowe Szwajcarii",
  "holiday.christmas": "Boże Narodzenie",
  "holiday.st_stephens": "Dzień św. Szczepana",
  "holiday.unknown": "{holiday}",

  // Impersonal on purpose — see the GENDER note in this file's header.
  "elig.in": "Możesz wejść",
  "elig.chk": "Zapytaj w obiekcie",
  "elig.no": "Nie dla Ciebie",
  "elig.chk.short": "Zapytaj",

  "pill.open": "Otwarte",
  "pill.opensLater": "Otwarcie później",
  "pill.closed": "Zamknięte",
  "pill.unknown": "Godziny nieopublikowane",

  "badge.teachingPool": "Basen do nauki pływania",
  "badge.metres": "{length} m",
  "age.minutes": "{count} min",
  "age.hours": "{count} godz.",
  "age.days": {
    one: "{count} dzień",
    few: "{count} dni",
    many: "{count} dni",
    other: "{count} dnia",
  },
  "badge.poolAria": "Basen {length}-metrowy, {lanes}",

  "sources.label": "Źródła",
  "sources.official": "Strona oficjalna",
  "sources.lanePlan": "Plan torów",
  "sources.prices": "Cennik",
  "sources.pdf": "PDF",
  "sources.pdfLabel": "{label} PDF",
  "sources.chipAria": "{name} — otwiera {host} w nowej karcie",

  "combo.noMatches": "Brak wyników",
  "combo.noPoolsMatch": "Brak pasujących basenów",
  "place.useMyLocation": "Użyj mojej lokalizacji",
  "place.myLocation": "Moja lokalizacja",

  "date.selectedDay": "Wybrany dzień",
  "date.previousDay": "Poprzedni dzień",
  "date.nextDay": "Następny dzień",
  "date.selectedWeek": "Wybrany tydzień",
  "date.previousWeek": "Poprzedni tydzień",
  "date.nextWeek": "Następny tydzień",
  "date.weekOf": "Tydzień od {date}",

  "app.title": "Pływanie w Zurychu",
  "header.language": "Język",
  "header.copyLink": "Kopiuj link",
  "header.copied": "Skopiowano",
  "header.copyAria": "Skopiuj link do tego widoku",
  "header.themeAria": "Motyw: {theme} (kliknij, aby zmienić)",
  "theme.auto": "Automatyczny",
  "theme.light": "Jasny",
  "theme.dark": "Ciemny",

  "gantt.lane": "Tor {lane}",
  "gantt.public": "Publiczny",
  "gantt.reserved": "Zarezerwowany",
  "gantt.readout": "{hhmm} · {public} z {total} torów publicznych",

  "toolbar.label": "Filtry wyszukiwania",
  "toolbar.view": "Widok",
  "toolbar.viewMode": "Tryb widoku",
  "toolbar.mode.day": "Dzień",
  "toolbar.mode.pool": "Basen",
  "toolbar.near": "W pobliżu",
  "toolbar.wherefrom": "Skąd?",
  "toolbar.gender": "Płeć",
  "toolbar.gender.any": "Dowolna",
  "toolbar.gender.female": "Kobieta",
  "toolbar.gender.male": "Mężczyzna",
  "toolbar.gender.diverse": "Inna",
  "toolbar.age": "Wiek",
  "toolbar.age.any": "Dowolny wiek",
  "toolbar.age.child": "Dziecko",
  "toolbar.age.teen": "Nastolatek",
  "toolbar.age.adult": "Dorosły",
  "toolbar.age.senior": "Senior",
  "toolbar.lapOnly": "Tylko tory do pływania",
  "toolbar.busyness": "Obłożenie",
  "toolbar.busynessReason":
    "Obłożenie nie ma jeszcze źródła danych — niedostępne.",
  "toolbar.searchPool": "Szukaj basenu…",
  "toolbar.pool": "Basen",

  "detail.fact.today": "Dzisiaj",
  "detail.fact.basin": "Niecka",
  "detail.fact.distance": "Odległość",
  "detail.fact.price": "Cena",
  "detail.fact.water": "Woda",
  "detail.fact.liveWater": "Woda teraz",
  "detail.fact.eligibility": "Wstęp",
  "detail.fact.busyness": "Obłożenie",
  "detail.fact.freshness": "Aktualność",

  "price.adult": "Dorośli {amount}",
  "price.youth": "Młodzież {amount}",
  "price.child": "Dzieci {amount}",
  "price.senior": "Seniorzy {amount}",

  "detail.notListed": "Nieopublikowane",
  "detail.notShown": "Niepokazane",
  "detail.notDated": "Bez daty",
  "detail.notAvailable": "Niedostępne",
  "detail.notAvailableYet": "Jeszcze niedostępne",
  "detail.notYetMeasured": "Jeszcze niezmierzone",
  "live.not_configured": "Nieskonfigurowane",
  "live.provider_error": "Źródło niedostępne",
  "live.no_key": "Niedostępne",
  "detail.liveOpen": "otwarte",
  "detail.liveClosed": "zamknięte",
  "board.nearestFirst": "Najbliższe najpierw",
  "detail.waterNotPublished": "Temperatura wody nieopublikowana",
  "detail.tempMeasured": "zmierzona",
  "detail.liveMeasuredAgo": "zmierzona {age} temu",
  "detail.closedNote": "Zamknięte — {reason}. {note}",
  "detail.tempNominal": "nominalna (projektowa)",
  "detail.checked": "Sprawdzono {date}",
  "detail.weekButton": "Zobacz tydzień tego basenu →",
  "detail.pool": "Basen",
  "detail.openLaneSplit": "Otwarte · podział torów nieopublikowany",
  "detail.noPublicLanes": "Dziś brak torów publicznych",
  "detail.openRange": "Otwarte · {from}–{to}",
  "detail.closedReason": "Zamknięte · {reason}",
  "detail.hoursUnknown": "Godziny nieopublikowane — może być otwarte",
  "detail.headline": "z {total} torów publicznych · {hhmm}",
  "detail.peakNote": "szczyt {peak} z {total}",
  "detail.headlineAria":
    "{public} z {total} torów publicznych o {hhmm} (szczyt {peak})",
  "detail.note.lanesUnknown":
    "Dla tego basenu nie opublikowano jeszcze planu torów — godziny są opracowane, ale podział na tory publiczne i zarezerwowane już nie.",
  "detail.note.closed":
    "Ten basen jest tego dnia zamknięty z podanego powodu — nie łączymy tego z basenami, o których po prostu brakuje nam danych.",
  "detail.note.uncurated":
    "Znamy lokalizację tego basenu, ale nie mamy jeszcze harmonogramu. Brak danych to nie to samo co zamknięte — może być otwarty.",
  "detail.emptyPanel":
    "Kliknij dowolny basen, aby zobaczyć godziny, cenę i plan torów.",

  "prov.official": "Oficjalny harmonogram",
  "prov.illustrative": "Poglądowe — odczytane ze strony basenu",
  "prov.lastChecked": " · ostatnio sprawdzono {date}",

  "mobile.tier.now": "Popływaj teraz",
  "mobile.tier.soon": "Później dzisiaj",
  "mobile.tier.unknown": "Godziny nieopublikowane",
  "mobile.tier.closed": "Zamknięte",

  "mobile.verdict.openNow": "Otwarte teraz",
  "mobile.verdict.partlyReserved": "Częściowo zarezerwowane",
  "mobile.verdict.notYoursUntil": "Nie dla ciebie do {hhmm}",
  "mobile.verdict.opensAt": "Otwiera o {hhmm}",
  "mobile.verdict.doneForToday": "Na dziś koniec",
  "mobile.verdict.closedAllDay": "Zamknięte cały dzień",
  "mobile.verdict.hoursUnknown": "Godziny nieopublikowane",
  "mobile.verdict.untilTime": "do {hhmm}",
  "mobile.lanesUntil": "{public} z {total} torów publicznych do {hhmm}",

  "mobile.openToYou": {
    one: "{count} otwarty teraz dla ciebie",
    few: "{count} otwarte teraz dla ciebie",
    many: "{count} otwartych teraz dla ciebie",
    other: "{count} otwartego teraz dla ciebie",
  },
  "mobile.openToYouOn": {
    one: "{count} otwarty dla ciebie w {day}",
    few: "{count} otwarte dla ciebie w {day}",
    many: "{count} otwartych dla ciebie w {day}",
    other: "{count} otwartego dla ciebie w {day}",
  },
  "mobile.filters": "Filtry",
  "mobile.today": "Dzisiaj",
  "mobile.lanePlan": "Plan torów",
} as const satisfies CatalogFor<"pl">;

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
  "access.girls": "Tylko dla dziewcząt",
  "access.genderDiverse": "Osoby transpłciowe i niebinarne",
  "access.accompanied": "Dzieci tylko z osobą dorosłą",
  "legend.state.open": "Otwarte (tory publiczne)",
  "legend.state.closed": "Zamknięte — z podaniem powodu",
  "legend.state.unknown": "Godziny jeszcze nieopublikowane",
  // --- Stos torów (lane-stack-board S4) --------------------------------------------
  "legend.group.laneStack": "Stos torów",
  "legend.lane.public": "Tor otwarty dla publiczności",
  "legend.lane.reserved": "Tor zarezerwowany (nazwa, jeśli się mieści)",
  "legend.lane.best": "Najwięcej wolnych torów publicznych",
  "legend.lane.unpublished": "Podział torów nieopublikowany",

  "status.closed": "Zamknięte",
  "status.closed_reason": "Zamknięte · {reason}",
  "status.uncurated": "Godziny nieopublikowane",
  "status.awaiting_scrape": "Godziny jeszcze nieopublikowane",
  "status.no_source": "Godziny nieopublikowane",

  // seasonal-hours S4: per-SESSION fair-weather marker; {spans} are the conditional clock spans.
  "session.fairWeather": "Tylko przy ładnej pogodzie · {spans}",

  "closure.seasonal_break": "Przerwa letnia",
  "closure.seasonal_break_maintenance": "Przerwa letnia / remont",
  "closure.maintenance": "Remont",
  "closure.operational_break": "Przerwa zakładowa",
  "closure.christmas_eve": "Wigilia",
  "closure.public_holiday": "Dzień świąteczny",
  "closure.public_holiday_named": "{holiday}",
  "closure.no_sessions": "Brak zaplanowanych zajęć",
  // Neutralne sezonowo — nigdy „przerwa zimowa”.
  "closure.out_of_season": "Nieczynne poza sezonem",
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
  "board.noSessionsGroup": "Brak opublikowanych godzin na dziś",
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

  "prov.scraped": "Oficjalny harmonogram — pobrany ze strony basenu",
  "prov.awaiting": "Harmonogram jeszcze nieopublikowany",
  "prov.noSource": "Brak źródła harmonogramu dla tego basenu",
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
  // --- Natywna aplikacja iOS (native-ios-app S4) -----------------------------------
  "state.openUnscheduled": "Otwarte, ale godziny nieopublikowane",
  "state.beyondHorizon": "Poza opublikowanym horyzontem",
  "state.beyondHorizon.body":
    "Publikujemy odpowiedzi do {date}. To nie oznacza, że baseny są zamknięte — po prostu nie opracowaliśmy jeszcze tego dnia.",
  "state.notStated": "Stan niepodany",
  "state.unrecognised": "{status}",
  "state.closed.outOfSeason": "Zamknięte — poza sezonem",
  "state.closed.noSessions": "Zamknięte — brak zajęć",
  "state.closed.unmapped": "Zamknięte — „{text}”",
  "state.closed.unclassified": "Zamknięte — powód niesklasyfikowany",
  "state.closed.other": "Zamknięte — {code}",
  "state.closed.unstated": "Zamknięte — powód niepodany",

  "tier.scheduled": "Otwarte tego dnia",
  "verdict.notOpenToYou": "Nie dla Ciebie",
  "verdict.hasSessions": "Ma zajęcia",
  "headline.poolsWithSessions": {
    one: "{count} basen z zajęciami",
    few: "{count} baseny z zajęciami",
    many: "{count} basenów z zajęciami",
    other: "{count} basenu z zajęciami",
  },
  "row.moreToday": "+{count} więcej dzisiaj",
  "row.moreThatDay": "+{count} więcej tego dnia",

  "banner.calendarCoverage.title": "Niepełny kalendarz świąt",
  "banner.holidayHoursUnverified.title": "Godziny świąteczne niepotwierdzone",
  "banner.generic.title": "Uwaga",
  "warning.calendar_coverage":
    "Brak danych kalendarza na {year}; harmonogramy zależne od świąt mogą być niedokładne.",
  "warning.holiday_hours_unverified":
    "{date} to dzień świąteczny, a te baseny nie publikują swoich godzin świątecznych; pokazane godziny to ich zwykłe godziny dnia powszedniego i są niepotwierdzone: {pools}",
  "warning.unknown": "{code}",

  "access.public.desc":
    "Otwarte pływanie publiczne — w tych godzinach może wejść każdy.",
  "access.lane.desc":
    "Pływanie na torach (Bahnenschwimmen) — publiczne, z podziałem na tory do pływania i treningu.",
  "access.family.desc":
    "Zajęcia dla rodzin i dzieci — publiczne, pomyślane z myślą o rodzinach.",
  "access.women.desc":
    "Zajęcia tylko dla kobiet (Frauenbad / Frauenschwimmen) — zarezerwowane dla kobiet.",
  "access.seniors.desc":
    "Zajęcia dla seniorów — zarezerwowane dla gości od 60. roku życia.",
  "access.school.desc":
    "Zarezerwowane dla klas szkolnych — niedostępne publicznie.",
  "access.club.desc":
    "Zarezerwowane dla klubu lub stowarzyszenia — niedostępne publicznie.",
  "access.adults.desc":
    "Publiczne okno tylko dla dorosłych — zarezerwowane dla gości od 18. roku życia (typowe dla wieczornego pływania w basenach szkolnych).",
  "access.girls.desc":
    "Zajęcia tylko dla dziewcząt (für Mädchen) — basen nie podaje granicy wieku, więc potwierdź w obiekcie.",
  "access.genderDiverse.desc":
    "Zajęcia dla osób transpłciowych i niebinarnych od 16. roku życia.",
  "access.accompanied.desc":
    "Dla dzieci wyłącznie pod opieką osoby dorosłej (für Kinder nur mit Erwachsenen).",
  // Nigdy „pływanie publiczne” dla nieznanego rodzaju zajęć — to powód, by zapytać.
  "access.unknown": "Zajęcia — zapytaj w basenie",

  "poolKind.indoor": "Basen kryty",
  "poolKind.outdoor": "Basen odkryty",
  "poolKind.lake": "Kąpielisko jeziorne",
  "poolKind.river": "Kąpielisko rzeczne",
  "poolKind.thermal": "Basen termalny",
  "poolKind.school": "Basen szkolny",
  "poolKind.paddling": "Brodzik",
  "poolKind.unknown": "{kind}",

  "detail.section.where": "Gdzie",
  "detail.section.admission": "Wstęp",
  "detail.section.season": "Sezon",
  "detail.section.basins": "Niecki",
  "detail.section.features": "Udogodnienia",
  "detail.section.lockers": "Szafki",
  "detail.section.rentals": "Wypożyczalnia",
  "detail.section.lanes": "Plany torów",
  "detail.section.provenance": "Skąd pochodzą te dane",

  "detail.fact.address": "Adres",
  "detail.fact.phone": "Telefon",
  "detail.fact.website": "Strona",
  "detail.fact.about": "O obiekcie",
  "detail.fact.schedule": "Harmonogram",
  "detail.fact.entry": "Wstęp",
  "detail.fact.yourRate": "Twoja stawka",
  "detail.fact.pricesRead": "Ceny odczytano",
  "detail.fact.tariffPage": "Cennik",
  "detail.fact.lastAdmission": "Ostatnie wejście",
  "detail.fact.season": "Sezon otwarcia",

  "freshness.scraped": "Opublikowane przez basen",
  "freshness.awaiting": "Jeszcze nieopublikowane",
  "freshness.noSource": "Brak harmonogramu do odczytania",
  "freshness.unknown": "Nierozpoznany stan: {state}",
  "freshness.awaiting.caveat":
    "Ten basen ma stronę z harmonogramem, ale nie została ona jeszcze wczytana do tej aplikacji.",
  "freshness.noSource.caveat":
    "Ten basen nie publikuje własnego harmonogramu. To nie to samo co zamknięty.",
  "freshness.unknown.caveat":
    "Ta aplikacja nie rozpoznaje tego stanu; zapytaj w basenie.",

  "priceCategory.adult": "Dorośli",
  "priceCategory.youth": "Młodzież",
  "priceCategory.child": "Dzieci",
  "priceCategory.senior": "Seniorzy",
  "priceCategory.unknown": "{category}",
  "price.minAgeCaveat": "Opublikowane dla wieku od {minAge} lat.",
  "price.staleCaveat":
    "Ceny pochodzą ze strony samego basenu i mogą się zmienić bez uprzedzenia.",

  "admission.free": "Bezpłatny",
  "admission.tariff": "Płatny — zobacz cennik poniżej",
  // NIE „bezpłatny”: niepodany wstęp jest po prostu nieznany.
  "admission.unknown": "Nieopublikowany — zapytaj w basenie",
  "detail.lastAdmission.value": "{duration} przed zamknięciem",

  "season.range": "{from}–{to}",
  "season.rangeWithDays": "{startDay} {from} – {endDay} {to}",
  "season.fairWeatherCaveat":
    "Opublikowane dla ładnej pogody; przy złej pogodzie basen może nie otworzyć.",

  "basin.fact.size": "Wymiary",
  "basin.fact.lanes": "Tory",
  "basin.fact.water": "Woda",
  "basin.fact.diving": "Skoki",
  "basin.fact.lanePlan": "Plan torów",
  "basin.size.lengthByWidth": "{length} × {width}",
  "basin.size.length": "{length}",
  "basin.size.width": "szerokość {width}",
  "basin.tempNominalCaveat": "Temperatura podana przez basen, nie pomiar.",
  "basin.parsedProseCaveat":
    "Odczytane z opisu na stronie basenu, więc może być przybliżone.",
  "basinKind.swimmer": "Basen pływacki",
  "basinKind.non_swimmer": "Basen dla nieumiejących pływać",
  "basinKind.diving": "Basen do skoków",
  "basinKind.learner": "Basen do nauki pływania",
  "basinKind.paddling": "Brodzik",
  "basinKind.multi_purpose": "Basen wielofunkcyjny",
  "basinKind.thermal": "Basen termalny",
  "basinKind.outdoor": "Basen odkryty",
  "basinKind.unknown": "{kind}",

  "feature.fact.surcharge": "Dopłata",
  "feature.fact.temperature": "Temperatura",
  "feature.fact.hours": "Godziny tego dnia",
  "feature.hoursNotListed": "Godziny nieopublikowane na ten dzień",
  "feature.closed": "Zamknięte — {reason}",
  // Człony pisane małą literą — czytane WEWNĄTRZ `feature.closed`.
  "closureClause.out_of_season": "poza sezonem",
  "closureClause.no_sessions": "brak godzin opublikowanych na ten dzień",
  "closureClause.closure": "basen zgłasza zamknięcie",
  "closureClause.unknown": "{reason}",
  "featureKind.sauna": "Sauna",
  "featureKind.gastronomy": "Restauracja lub kiosk",
  "featureKind.sunbathing": "Trawnik do opalania",
  "featureKind.playground": "Plac zabaw",
  "featureKind.slide": "Zjeżdżalnia wodna",
  "featureKind.wellness": "Strefa wellness",
  "featureKind.sport": "Obiekt sportowy",
  "featureKind.unknown": "{kind}",

  "lockerKind.wardrobe": "Szafka na ubrania",
  "lockerKind.valuables": "Skrytka na kosztowności",
  "lockerKind.cabin": "Kabina do przebierania",
  "lockerKind.unknown": "{kind}",
  "rentalKind.towel": "Ręcznik",
  "rentalKind.locker": "Szafka",
  "rentalKind.deck_chair": "Leżak",
  "rentalKind.swim_aid": "Sprzęt do pływania",
  "rentalKind.unknown": "{kind}",
  "fee.free": "Bezpłatne",
  "fee.unstated": "Cena nieopublikowana",
  "fee.amount": "{amount}",
  "fee.perPeriod": "za {period}",
  "fee.deposit": "kaucja {amount}",

  "panel.bestWindow": {
    one: "{start}–{end}, {count} tor",
    few: "{start}–{end}, {count} tory",
    many: "{start}–{end}, {count} torów",
    other: "{start}–{end}, {count} toru",
  },
  // Formę wybiera liczba torów wypisanych w {lanes}; forma ułamkowa nie wystąpi tu
  // w praktyce, ale musi być odrębna.
  "panel.clubSlot.oneLane": "{start}–{end}, tor {lanes}",
  "panel.clubSlot.manyLanes": "{start}–{end}, tory {lanes}",
  "prov.fact.readFrom": "Odczytane ze",
  "prov.fact.accurateAsOf": "Aktualne na",
  "prov.fact.curation": "Opracowanie",
  "prov.curated.yes": "Sprawdzone ręcznie",
  "prov.curated.no": "Odczytane wprost ze strony basenu",

  // --- Plany torów -----------------------------------------------------------------
  "lane.incompleteCaveat":
    "Nie wszystkie tory udało się odczytać z planu basenu, więc dane są niepełne.",
  "lane.nonePublic": "brak torów otwartych dla publiczności",
  "lane.nonePublic.partial":
    "brak torów otwartych dla publiczności — niektórych torów nie odczytano",
  "lane.publicOfTotal": {
    one: "otwarty {public} z {count} toru",
    few: "otwarte {public} z {count} torów",
    many: "otwartych {public} z {count} torów",
    other: "otwarte {public} z {count} toru",
  },
  "lane.publicOfTotal.partial": {
    one: "otwarty {public} z {count} toru — niektórych torów nie odczytano",
    few: "otwarte {public} z {count} torów — niektórych torów nie odczytano",
    many: "otwartych {public} z {count} torów — niektórych torów nie odczytano",
    other: "otwarte {public} z {count} toru — niektórych torów nie odczytano",
  },
  "lane.openToPublic": "otwarty dla publiczności",
  "lane.spoken": "Tor {lane}, {start} do {end}, {holder}",

  // --- VoiceOver nad wstęgą ---------------------------------------------------------
  "a11y.blockLabel": "{start} do {end}, {access}",
  "a11y.fact.publicLanes": "Tory otwarte dla publiczności",
  "a11y.value.ofTotal": "{public} z {total}",
  "a11y.fact.laneData": "Dane o torach",
  "a11y.value.laneDataIncomplete": "niepełne dla tej niecki",
  "a11y.fact.lanes": "Tory",
  "a11y.fact.reservedBy": "Zarezerwowane przez",
  "a11y.value.ownerAndOthers": "{owner} i inni",
  "a11y.fact.laneSplit": "Podział torów",
  "a11y.value.laneSplitUnpublished": "nieopublikowany dla tego basenu",
  "a11y.selected": "Wybrane",

  // --- Elementy interfejsu telefonu -------------------------------------------------
  "nav.map": "Mapa",
  "nav.list": "Lista",
  "action.directions": "Trasa",
  "action.call": "Zadzwoń",
  "action.openInMaps": "Otwórz w Mapach",
  "nav.allPools": "Wszystkie baseny",
  "nav.accessTypes": "Co oznaczają etykiety",
  "nav.browse": "Przeglądaj",
  "nav.findAPool": "Znajdź basen",
  "accessTypes.title": "Rodzaje zajęć",
  "accessTypes.footer":
    "Zawsze decydują zasady samych zajęć: aplikacja pokazuje to, co basen publikuje na daną godzinę, a to są kategorie, do których je przypisuje.",
  "browser.noMatch.body": "Spróbuj innej nazwy albo innego rodzaju.",
  "browser.filterByKind": "Filtruj według rodzaju",
  "browser.kind": "Rodzaj",
  "browser.allKinds": "Wszystkie rodzaje",
  "gantt.title": "Tory, godzina po godzinie",
  "error.store.title": "Nie można odczytać danych o basenach",
  "error.store.body":
    "Nie udało się otworzyć dołączonych danych o basenach, więc nie ma czego pokazać. Ponowna instalacja aplikacji je przywróci.",
  "state.none.body.phone":
    "Spróbuj większego obszaru, innego dnia albo mniejszej liczby filtrów. To nie to samo co zamknięte.",
  "meta.dataFrom": "Dane z",
  "meta.answersThrough": "Odpowiedzi do",
  "meta.offlineNote":
    "Działa offline. Wszystko tutaj opracowano przed wydaniem aplikacji.",
  "action.favourite": "Dodaj do ulubionych",
  "action.unfavourite": "Usuń z ulubionych",
  "action.showLanePlan": "Pokaż plan torów",
  "action.hideLanePlan": "Ukryj plan torów",
  "action.done": "Gotowe",
  "session.fairWeather.badge": "Tylko przy ładnej pogodzie",
  "filter.none": "Bez filtrów",
  "filter.section.who": "Kto",
  "filter.section.where": "Gdzie",
  "filter.section.what": "Co",
  "filter.eligibleOnly": "Tylko otwarte dla mnie",
  "filter.eligibleOnly.toggle": "Tylko zajęcia otwarte dla mnie",
  "filter.favourites": "Ulubione",
  "filter.favouritesOnly.toggle": "Tylko moje ulubione",
  "filter.measureFrom": "Mierz od",
  "filter.within": "W promieniu",
  "filter.anyDistance": "Dowolna odległość",
  "filter.poolKinds": "Rodzaje basenów",
  "filter.allKinds": "Wszystkie",
  "place.anywhere": "Wszędzie",
  "place.searchPrompt": "Szukaj miejsc",
  "place.hb": "Zurych HB (dworzec główny)",
} as const satisfies CatalogFor<"pl">;

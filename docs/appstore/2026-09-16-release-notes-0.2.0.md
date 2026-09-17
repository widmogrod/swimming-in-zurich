# Release notes — SwimZH 0.2.0

The second App Store release, and the first since 0.1.3 passed App Review on 2026-08-28 (tag
`v0.1.3`, PR #9). Everything below is what `main` has gained since that tag: PRs #10, #12 and #13,
plus this branch. Cut it by publishing a GitHub Release tagged `v0.2.0` — `release.yml` derives the
marketing version from the tag and submits with `automatic_release`, so publishing the release is
the whole act.

**Why 0.2.0 and not 0.1.4:** the app now requires iOS 27. A 0.1.3 phone on iOS 26 cannot install
this build, and the store listing's minimum OS changes with it. That is a compatibility break, and
the minor bump says so.

---

## GitHub Release body (paste as-is)

### SwimZH 0.2.0 — the iOS 27 release

**Requires iOS 27.** The deployment target moved from 26.0 to 27.0 so the whole app can use Liquid
Glass without `#available` branches. iOS 26 devices keep 0.1.3.

#### For swimmers

- **Pool screen is a map.** Opening a pool lands on a full-screen map with the pool's facts in a
  glass drawer that rests at three heights; drag it down past the smallest to go back. The screen
  leads with what matters at the door — water temperature, length and lane count — and offers the
  lane plan behind it.
- **Liquid Glass throughout.** The day strip morphs its selection chip to chip, the map's pin card
  and the tab bar are glass, and the favourite heart and filter glyph animate.
- **Filters are a tab.** Age, gender, pool type and radius live on their own tab; the chips scale
  and fade in, and the list updates immediately.
- **Search keeps your place.** Searching suggests pool names and returns you to the page you
  came from.
- **Web links open inside the app.** The pool's own page and directions open in an in-app browser.
- **Pull to check for newer data.** Pull the list down to fetch a fresher pool store if one has
  been published; the About screen shows what is loaded and how fresh each source is.
- **Ready for a wide window.** On a wide screen the map fills the window with the list floating
  over it — laid out for the unfolded phone.
- **A layered app icon** with depth in all four Home Screen icon modes.
- **Holiday hours for 2027.** The bundled calendar now carries the 2027 public holidays, so the
  four pools that run Sunday hours on a Feiertag resolve correctly through the whole 400-day
  horizon and the "calendar data not available" warning no longer shows on 2027 dates.

#### Under the hood

- **Weekly data refresh without a release.** A scheduled workflow publishes a fresh pool store
  every Monday; installed apps adopt it after validating bytes, checksum, schema and integrity.
- **A code-owned data lake.** The build keeps each source's last good result as typed silver, so
  a city page that is temporarily down no longer aborts the whole build — the store ships with
  that source marked stale and `/health` says so.
- **CI archives on Xcode 27.** Both the QA job and the release job run on GitHub's `xcode-27`
  image, the only hosted image with an iOS 27 SDK. 0.1.3 was archived with Xcode 26 and cannot
  be rebuilt that way any more.
- The all-pools browser and the Lab switches used to compare the old and new looks on a phone
  were removed once every look was decided.

**Full Changelog**: https://github.com/widmogrod/swimming-in-zurich/compare/v0.1.3...v0.2.0

---

## App Store Connect — "What's New in This Version"

The listing is maintained by hand in App Store Connect (`fastlane` uploads with `skip_metadata`),
so paste each block into its locale. Keep the English one under 4000 characters; the rest are
translations of the same claims and nothing more.

### English

```
Requires iOS 27.

• Every pool opens on a map, with its facts in a drawer you drag up and down. Water temperature, length and lane count come first.
• Filters have their own tab: age, gender, pool type and distance.
• Search suggests pool names and keeps your place.
• Pull the list down to check for newer pool data. The About screen shows how fresh it is.
• A wide window shows the map with the list floating over it.
• New app icon.
• 2027 public holidays are included, so holiday opening hours resolve for the year ahead.
```

### Deutsch

```
Benötigt iOS 27.

• Jedes Bad öffnet auf einer Karte, die Fakten in einer Schublade zum Hoch- und Runterziehen. Wassertemperatur, Beckenlänge und Bahnen zuerst.
• Filter haben einen eigenen Tab: Alter, Geschlecht, Badtyp und Distanz.
• Die Suche schlägt Badnamen vor und merkt sich, wo du warst.
• Liste nach unten ziehen, um neuere Baddaten zu laden. Der Info-Bildschirm zeigt, wie aktuell sie sind.
• Ein breites Fenster zeigt die Karte mit der Liste darüber.
• Neues App-Icon.
• Die Feiertage 2027 sind enthalten, damit Feiertagsöffnungszeiten für das kommende Jahr stimmen.
```

### Français

```
Nécessite iOS 27.

• Chaque piscine s'ouvre sur une carte, ses informations dans un panneau à faire glisser. Température de l'eau, longueur et nombre de couloirs d'abord.
• Les filtres ont leur propre onglet : âge, genre, type de piscine et distance.
• La recherche propose des noms de piscines et garde votre page.
• Tirez la liste vers le bas pour vérifier s'il existe des données plus récentes. L'écran À propos indique leur fraîcheur.
• Une fenêtre large affiche la carte avec la liste par-dessus.
• Nouvelle icône.
• Les jours fériés 2027 sont inclus, pour des horaires corrects toute l'année à venir.
```

### Italiano

```
Richiede iOS 27.

• Ogni piscina si apre su una mappa, con i dati in un pannello da trascinare. Temperatura dell'acqua, lunghezza e corsie per primi.
• I filtri hanno una scheda propria: età, genere, tipo di piscina e distanza.
• La ricerca suggerisce i nomi delle piscine e ricorda dove eri.
• Trascina la lista verso il basso per cercare dati più recenti. La schermata Info mostra quanto sono aggiornati.
• Una finestra larga mostra la mappa con la lista sopra.
• Nuova icona.
• I giorni festivi 2027 sono inclusi, così gli orari festivi sono corretti per l'anno a venire.
```

### Polski

```
Wymaga iOS 27.

• Każdy basen otwiera się na mapie, a jego dane są w szufladzie, którą przeciągasz w górę i w dół. Temperatura wody, długość i liczba torów na pierwszym miejscu.
• Filtry mają własną kartę: wiek, płeć, rodzaj basenu i odległość.
• Wyszukiwanie podpowiada nazwy basenów i pamięta, gdzie byłeś.
• Pociągnij listę w dół, aby sprawdzić nowsze dane o basenach. Ekran „O aplikacji” pokazuje, jak są aktualne.
• Szerokie okno pokazuje mapę z listą nad nią.
• Nowa ikona aplikacji.
• Dodano święta 2027, więc godziny otwarcia w święta są poprawne na cały nadchodzący rok.
```

---

## Before tagging

- **Which Xcode 27 the image has.** GitHub merged the Release Candidate toolset (`27A266a`) into
  `xcode-27` on 2026-09-11 (`actions/runner-images#14718`), but the deployed image still
  reported beta 6 (`27A5252f`) on PR #14's green `ios-qa` run of 2026-09-16. App Store Connect
  accepts uploads built with a release-quality SDK only, so before tagging check the
  "Show Xcode" line of the latest `ios-qa` run: `27A266a` (or later) means go; `27A5252f` means
  wait for the image rebuild, or the upload will be rejected for a beta SDK.
- The release job has not run on `xcode-27` yet. `release.yml`'s own header records that a
  `dry_run` skips the two Apple-facing steps: run one anyway, because the archive and signing are
  exactly what changed image.
- Still open from the pre-release checklist: a native-speaker read of the Polish and German
  catalogs, and a real-device pass over the new screens.

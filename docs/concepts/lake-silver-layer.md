# The lake: a code-owned raw → silver → gold pipeline

**Decision (2026-09-05).** The build pipeline owns its own three-layer lake. The host that
triggers a build — a laptop, GitHub Actions, a server later — supplies exactly three things: a
trigger, a lake location, and a publish target. Nothing about the layers, the cadence, or the
provenance lives in a workflow file, a bot commit, or a CI cache.

## Why

On 2026-09-04 the city's WFS host answered `HTTP 500` to everything. `swimzh build` fetches the
roster first, so the whole build died in one second and nothing else was even asked. The Monday
refresh would have failed the same way and silently kept the previous week's store online.

The first fix considered — fall back to the committed `data/catalog.json` — patched one source and
put a hand-made file on the path. The second — bot-committed silver files plus one workflow per
source — solved the provenance question but moved the pipeline into GitHub. This design keeps the
pipeline in `swimzh build`.

## The layers (`storage/lake.py`)

| layer  | what                                          | where                          | published |
|--------|-----------------------------------------------|--------------------------------|-----------|
| raw    | the provider HTTP cache: the city's own bytes | `.cache/swimzh/` (as before)   | never     |
| silver | one typed JSON document per source, with a header | `.lake/silver/<source>.json` | yes, beside the store |
| gold   | the composed SQLite store                     | `gold.sqlite`                  | as the iOS export |

Silver sources, in pipeline order: `roster`, `prices`, `schedules`, `lane_plans`
(`SILVER_SOURCES`). Each document is `{"silver": header, "payload": object}` where the header is
`schema`, `source`, `fetched_at`, `status ∈ {fresh, stale}`, `content_sha`. A document under another
`schema` reads as absent (a first run), never as input to today's codec. `content_sha` skips the
run stamps (`fetched_at`, `generated_at`, `valid_as_of`), so it changes only when the facts do. Payload codecs
(`etl/silver_codec.py`) reuse the codecs gold already trusts — the catalog codec, the boundary
price/lane-plan DTOs, and the gold facility blob for the scraped-side facilities — so nothing can
survive gold and not survive silver.

Raw stays private because it is the city's content; silver is ours, so it may be hosted.

## What one run does, per source (`etl/refresh.py`)

| silver state                                            | fetch | result                    | status |
|---------------------------------------------------------|-------|---------------------------|--------|
| younger than the source's TTL                           | no    | reuse as is               | fresh  |
| due, site answers 200, parse OK                         | yes   | new document              | fresh  |
| due, transient failure (timeout, refused, 5xx), age ≤ max_stale | tried | keep the old document | stale |
| due, transient failure, age > max_stale                 | tried | **abort**, prior gold untouched | — |
| 200 that will not parse (schema drift)                  | yes   | **abort**                 | — |
| no document at all, site down (first run)               | tried | **abort**                 | — |

`ttl_s` and `max_stale_s` are two columns of the one table in `core/cache_tiers.py`. A daily cron
and a weekly cron produce the same lake: cadence is the TTL, not the trigger.

Exit codes: `0` every source fresh; `2` built, at least one source kept stale; `1` aborted (or the
pre-existing benign unresolved-name miss). Exit 2 is a **complete** store — every phase ran, one
of them on last time's silver — not a partial one; the atomic swap invariant is unchanged.

## Provenance, end to end

* gold: `source_freshness` (source, fetched_at, status, content_sha, built_at), written last.
* `/health`: `sources[]` with `age_days`, read from that table.
* the iOS manifest: `freshness[]` (source, fetched_at, status), read back out of the exported
  store's `meta.source_freshness` like every other manifest field. Additive; old clients ignore it.
* the build's stdout: one `sources:` line naming, per source, fetched-or-reused and when.

## The runtime contract

```sh
swimzh lake pull <dir-or-http-base>   # step 0: seed .lake/silver from the last publish (best effort, loud)
swimzh build --db gold.sqlite --lake .lake
swimzh lake export --out dist/ios/lake   # ships beside the store; the next run pulls it
```

GitHub Actions runs exactly those three lines (`publish-store.yml`), pulling from the Pages URL
the store is served from and accepting exit 2 with a warning annotation. A laptop runs the same
three lines against a local folder. `--refresh` forces every source to refetch regardless of TTL.

## What was deliberately not done

* No bot commits of silver into git; no one-workflow-per-source. Both are host-specific
  shapes of what the refresh policy already does in process.
* No hand-made fallback catalog. `data/catalog.json` remains what it was (the `scrape-gold`
  re-layer's roster double); the lake's `roster.json` is the build's own.
* The thin re-layer commands (`scrape-gold`, `scrape-lanes`) run their fetch + write halves back
  to back without the lake, as before.

## Verified 2026-09-06, live

Old code (main) and new code built from the live sites minutes apart: the gold stores were
identical row for row except `fetched_at` and the new `source_freshness` table; the iOS exports
had the same `content_hash`. The audit caught one regression — the roster silver dropped the WFS
`poi_id`, so a lake-warm build nulled `geo_sport_id` and lost 25 xrefs — fixed the same day
(`catalog_json` now carries `poi_id`; the silver `schema` guards against a pre-fix document).
Timings on one laptop: old cold 13.1 s, old warm HTTP cache 1.2 s, new cold 9.4 s, new warm lake
0.2 s with the network off. The lake adds about 0.05 s to a live build.

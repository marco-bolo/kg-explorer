# MARCO-BOLO KG Explorer

Interactive knowledge graph of the MARCO-BOLO metadata catalog.

> Forked from **[sdiggs/kg-explorer](https://github.com/sdiggs/kg-explorer)** by
> Steve Diggs. Steve's original explorer was designed for interview-extracted
> JSON datasets; this fork adapts it to consume the schema.org-compacted
> JSON-LD produced by the [marco-bolo/csv-to-json-ld](https://github.com/marco-bolo/csv-to-json-ld)
> pipeline. The renderer (sigma.js + d3-force), the chrome, and the
> drop-JSON-to-overlay workflow are all Steve's. `build_data.py` and the
> graph-building JS are MBO-specific.

## Live tool

`https://marco-bolo.github.io/kg-explorer/`

## Data flow

```
   csv-to-json-ld pipeline (Google Sheets → JSON-LD)
            │
            ▼
   remote/models/schema-jsonld/
   ├── mbo_<uuid>.json              one per entity
   └── mbo_<uuid>-input-metadata.json   one provenance sidecar per entity
            │
            ▼  (build_data.py, scheduled GitHub Action)
   data.json   (single bundle: nodes, edges, WP attribution, orphan list)
            │
            ▼  (index.html, auto-loads on page open)
   rendered knowledge graph in browser
```

The explorer never reads CSVs. It consumes the canonical published JSON-LD,
so whenever the upstream pipeline rebuilds, the graph catches up on the next
scheduled run (every 6 hours, or sooner via `workflow_dispatch`).

## Repository layout

```
index.html                       ← the explorer (Steve's chrome, MBO graph logic)
data.json                        ← pre-built KG (auto-loaded; refreshed by CI)
build_data.py                    ← JSON-LD → KG bundler
build_data.py.steve.bak          ← Steve's original, preserved for provenance
.github/workflows/
  refresh-and-deploy.yml         ← scheduled rebuild + Pages deploy
approved/.gitkeep                ← (inherited) future per-entity overlays
README.md
.gitignore
```

## How the build works

`build_data.py` walks `schema-jsonld/`:

1. **Nodes** — one per entity file. The `@id` becomes the node id; the `@type`
   maps to a coarse `kind` (`task`, `deliverable`, `dataset`, `document`,
   `howto`, `person`, `org`, `place`, `instrument`, `platform`, ...). The
   label comes from `name`, falling back to `givenName + familyName`, `title`,
   `termCode`, or the @id.
2. **Edges** — every `{"@id": ...}`-shaped property value becomes a directed
   edge from the subject to the referenced @id, with `kind` = the property
   name (`result`, `agent`, `author`, `actionProcess`, `step`, etc.).
3. **Provenance edges from sidecars** — each `mbo_<uuid>-input-metadata.json`
   contributes two edges per entity: `wasResultOf` (from `@reverse.result`,
   the Action under which the row was entered) and `metadataEnteredBy`
   (from `creator`).
4. **WP attribution** — for each node, try (a) parsing "Task N" / "Deliverable
   N" / "WPN" from its own name, then (b) walk up via the sidecar's parent
   Action, then (c) walk up via inbound `result` edges. Unattributed
   entities (project-wide vocabulary, global Place entries) get `wp: null`.
5. **Orphan detection** — Tasks and Deliverables with no outbound production
   edge (`result`, `step`, `distribution`, `encodesCreativeWork`).

Output: a single `data.json`, currently ~700 KB for ~700 entities, ~2800 edges.

## Running locally

```bash
# clone csv-to-json-ld next to this repo, then:
python build_data.py --src ../csv-to-json-ld/remote/models/schema-jsonld --out data.json

# or point at any directory of JSON-LD files
python build_data.py --src ./schema-jsonld --check    # dry run
```

## What you can do in the tool

- **Filter by Work Package** — top filter bar, WP1–WP7 or "(none)".
- **Search** by mPID (UUID) or label.
- **Color modes**:
  - *Kind* — colours by @type (task / deliverable / dataset / etc.).
  - *WP* — colours by Work Package; cross-WP linkages pop out.
  - *Orphans* — green for Task/Deliverable hubs that have produced something,
    red for hubs with no outbound production edge. The single fastest view
    for spotting catalog gaps.
- **WP Coverage heatmap** (left panel) — rows are entity kinds, columns are
  WPs, cell shade is volume. The whole catalog-gap picture in one tile.
- **Drag-and-drop** any additional JSON bundle to overlay it on the
  auto-loaded `data.json`.
- **Export GEXF** for deeper analysis in Gephi.

## Deployment

The included GitHub Action runs `build_data.py` against the upstream JSON-LD
on schedule and deploys to Pages. To set up:

1. Push this repo to `marco-bolo/kg-explorer` (or wherever).
2. In Settings → Pages, set Source to "GitHub Actions".
3. The first push to `main` triggers the build.

## Provenance

This is a fork — `git log` will show Steve Diggs's commits as ancestors of
the MBO-specific work. The original interview-data version is also kept in
`build_data.py.steve.bak` for reference.

## Built with

[graphology](https://graphology.github.io/), [sigma.js](https://www.sigmajs.org/),
and [d3-force](https://github.com/d3/d3-force) — same stack as Steve's
kg-explorer. CDN-loaded; no build step needed.

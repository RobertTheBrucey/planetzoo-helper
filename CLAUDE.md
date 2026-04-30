# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A single-page Planet Zoo habitat planning tool. The entire application — HTML, CSS, and JavaScript — lives in `index.html`. There is no build system, no dependencies, and no tests. To preview locally, just open `index.html` in a browser or serve it with any static file server (e.g. `python3 -m http.server`).

Deployment is via Cloudflare Pages:
- `main` branch → production
- `staging` branch → staging subdomain (shows a build timestamp badge when `window.location.hostname.startsWith('staging.')`)

`_headers` sets security headers. `_redirects` routes all paths to `index.html`.

## Architecture

Everything is in `index.html`, structured in this order:

1. **HTML** — two-column layout: left panel (filters + animal list), right panel (habitat requirements)
2. **CSS** — inside `<style>`, uses CSS custom properties (`--bg`, `--text`, `--border`, etc.) for the dark theme
3. **JavaScript** — inside a single `<script>` block, divided by `// ===== SECTION =====` comments:
   - `DATA` — `ANIMALS` array (~130 entries, each one line), plus `CONTINENTS`, `BIOMES`, `PACKS`, color maps
   - `STATE` — module-level `let` vars: `selectedIds` (Set), `activePacks/Biomes/Continents` (Sets), `options` object, `searchQuery`
   - `HELPERS` — pure functions: `getSelectedAnimals()`, `getCombinedContinents/Biomes()`, `getTerrainRanges()`, `isCompatibleWith()`, `passesFilters()`
   - `RENDER` — `renderFilters()`, `renderAnimalList()`, `renderRightPanel()`, `renderTerrainSection()`, `findEnrichmentGroups()`
   - `INIT` — event listeners, initial `renderAll()` call, staging badge injection

`renderAll()` calls `renderFilters()`, `renderAnimalList()`, and `renderRightPanel()` — these do full DOM replacement via `innerHTML`/`insertAdjacentHTML`. There is no virtual DOM or diffing; re-renders are cheap because the lists are small.

## Animal data schema

Each habitat animal entry in `ANIMALS`:
```js
{
  id: 'snow_leopard',          // snake_case, unique
  name: 'Snow Leopard',
  latin: 'Panthera uncia',
  pack: 'Standard',            // DLC pack name
  continents: ['Asia'],
  biomes: ['Taiga'],
  img: 'panthera_uncia',       // Azure blob filename (no extension)
  enrichedBy: ['...'],         // names (not ids) of enrichment partners
  guestWalk: false,
  exhibit: false,              // true = exhibit animal (no terrain/barrier requirements)
  terrain: {
    grassS: [min, max],        // % coverage ranges, 6 types
    grassL: [min, max],
    soil:   [min, max],
    rock:   [min, max],
    sand:   [min, max],
    snow:   [min, max],
  },
  plants: [min, max],          // plant coverage %
  barrier: { grade: 2, height: 1.25 },  // absent on exhibit animals
}
```

Exhibit animals have `exhibit: true` and no `barrier` field; they are excluded from terrain/barrier calculations.

## Key logic

**Compatibility** (`isCompatibleWith(animal)`): checks continent, biome, terrain ranges, and plant coverage overlap against current selection. Returns false if adding the animal would create an impossible habitat. Controls the grey-out/hide behaviour in the animal list.

**Terrain ranges**: combined viable range = `[max of all mins, min of all maxes]`. Conflict when `cMin > cMax`. Total of all `cMin` values must not exceed 100%.

**Barrier requirements**: displayed as the `max(grade)` and `max(height)` across all selected non-exhibit animals.

**Enrichment groups** (`findEnrichmentGroups()`): finds cliques of mutually-enriching animals among the selection.

## Adding a new animal

Add one line to the `ANIMALS` array (keep alphabetical order). Source terrain/plant data from the in-game Zoopedia. Source barrier data from the [Planet Zoo wiki API](https://planetzoo.fandom.com/api.php?action=query&titles=Animal_Name&prop=revisions&rvprop=content&format=json) — look for the `fencegrade` field in the infobox, formatted as `grade >heightm` (e.g. `3 >3m`).

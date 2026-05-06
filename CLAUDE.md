# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A single-page Planet Zoo habitat planning tool. The entire application — HTML, CSS, and JavaScript — lives in `index.html`. There is no build system, no dependencies, and no tests. To preview locally, just open `index.html` in a browser or serve it with any static file server (e.g. `python3 -m http.server`).

Deployment is via Cloudflare Pages:
- `main` branch → production
- `staging` branch → staging subdomain (shows a build timestamp badge when `window.location.hostname.startsWith('staging.')`)

`_headers` sets security headers. `_redirects` routes all paths to `index.html`.

## Architecture

The app is two files:

- **`animals.js`** — the `ANIMALS` array (~169 entries, each one line). Edit this when adding or updating animal data.
- **`index.html`** — everything else: HTML, CSS, and application JS.

`index.html` is structured in this order:

1. **HTML** — two-column layout: left panel (filters + animal list), right panel (habitat requirements)
2. **CSS** — inside `<style>`, uses CSS custom properties (`--bg`, `--text`, `--border`, etc.) for the dark theme
3. **`<script src="animals.js">`** — loads the ANIMALS array before the main script
4. **JavaScript** — inside a single `<script>` block, divided by `// ===== SECTION =====` comments:
   - `DATA` — `CONTINENTS`, `BIOMES`, `PACKS` arrays, color maps (ANIMALS itself lives in `animals.js`)
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
  img: 'snow_leopard',         // filename in img/ (no extension; equals animal id)
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

Add one line to the `ANIMALS` array in `animals.js` (keep alphabetical by `name`). Source terrain/plant data from the in-game Zoopedia. Source barrier data from the [Planet Zoo wiki API](https://planetzoo.fandom.com/api.php?action=query&titles=Animal_Name&prop=revisions&rvprop=content&format=json) — look for the `fencegrade` field in the infobox, formatted as `grade >heightm` (e.g. `3 >3m`).

For bulk data extraction from game files, use `extract_pz_data.py`:
```
python extract_pz_data.py --cobra-tools PATH_TO_COBRA_TOOLS --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Planet Zoo"
```
This writes `extracted_animals.json` and `extracted_animals.js` with formatted ANIMALS entries ready to paste in. It also automatically extracts missing animal portrait images from the game's `AnimalSpeciesZoopedia` OVLs into `img/`.

Optional image flags:
- `--skip-images` — skip image extraction entirely
- `--images-all` — re-extract all portraits from game files, overwriting any already in `img/`

Requires the `imageio` Python package (`pip install imageio`) for texture conversion.

## Animal portrait images

Images live in `img/` as `<app_id>.png` where `app_id` is the animal's `id` field in `animals.js` (e.g. `snow_leopard.png`). The `img` field in each animal entry is the filename without extension.

Portraits are extracted directly from the game's `AnimalSpeciesZoopedia` OVLs by `extract_pz_data.py` (see above). No external downloads are needed.

**To add images manually**: place a `.png` file named `<app_id>.png` in `img/`. The `onerror` fallback in `getImgUrl()` shows a paw-print placeholder if the file is missing.

## External resources

All external resources (fonts, images) are bundled locally — there are no CDN links in production:
- **Fonts**: `fonts/` — Cinzel and Crimson Pro, loaded via `fonts/fonts.css`
- **Images**: `img/` — animal portraits

If you add a new font or icon set, download it and serve it locally. Do not add `<link>` tags pointing to Google Fonts, jsDelivr, or other external CDNs.

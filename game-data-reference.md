# Planet Zoo Game Data Reference

Where each field in `animals.js` comes from in the game files, and how `extract_pz_data.py` retrieves it.

---

## Game file structure

Animal data is stored in OVL archives, one per content pack:

```
<game>/win64/ovldata/
  Content0/Main.ovl        ← BaseGame ("Standard")
  Content1/Main.ovl        ← Arid
  Content2/Main.ovl        ← Africa
  Content3/Main.ovl        ← North America
  Content4/Main.ovl        ← Arctic
  Content5/Main.ovl        ← South America
  Content6/Main.ovl        ← Southeast Asia
  Content7/Main.ovl        ← Australia
  Content8/Main.ovl        ← Conservation
  Content9/Main.ovl        ← Wetlands
  Content10/Main.ovl       ← Europe
  Content11/Main.ovl       ← Eurasia
  Content12/Main.ovl       ← Grasslands
  Content13/Main.ovl       ← Tropical
  Content14/Main.ovl       ← Oceania
  Content15/Main.ovl       ← Twilight
  Content16/Main.ovl       ← Eurasia (2nd)
  Content17/Main.ovl       ← Barnyard
  Content18/Main.ovl       ← Zookeepers
  Content19/Main.ovl       ← Americas
  Content20/Main.ovl       ← Asia
  ContentAnniversary/      ← Anniversary packs
  GameMain/Main.ovl        ← Engine/UI data — not queried
```

Each content pack also has a localisation archive:

```
  Content*/Localised/English/UnitedKingdom/Loc.ovl
```

`extract_pz_data.py` uses [cobra-tools](https://github.com/OpenNaja/cobra-tools) (`ovl_tool_cmd.py extract`) to unpack each `Main.ovl` into `.fdb` files (standard SQLite databases) and each `Loc.ovl` into `.txt` files.

---

## FDB files inside each Main.ovl

| File pattern | Contains |
|---|---|
| `*animals.fdb` | All habitat animal definitions and requirements |
| `*zoopedia.fdb` | Barrier/fence requirements |
| `*exhibits.fdb` | Exhibit animal definitions |

The file is matched by suffix — e.g. `content17animals.fdb`, `basegameanimals.fdb`.

---

## `*animals.fdb` — schema and field mapping

Raw terrain/plant values are stored as floats in `0.0–1.0`; the script multiplies by 100 and rounds to produce the integer percentages shown in the app (0–100%).

| Table | Relevant columns | → `animals.js` field |
|---|---|---|
| `AnimalTerrainRequirements` | `AnimalType`, `MinShortGrass`, `MaxShortGrass`, `MinLongGrass`, `MaxLongGrass`, `MinOverallSoil`, `MaxOverallSoil`, `MinOverallRock`, `MaxOverallRock`, `MinOverallSand`, `MaxOverallSand`, `MinSnow`, `MaxSnow` | `terrain.grassS/grassL/soil/rock/sand/snow` each as `[min, max]` |
| `AnimalHabitatRequirements` | `AnimalType`, `MinPlantCoverage`, `MaxPlantCoverage` | `plants` as `[min, max]` |
| `SpaceRequirements` | `AnimalType`, `MinimumSpace` | `landMin` (m²) |
| `AnimalDefinitions` | `AnimalType`, `ContentPack` | `pack` |
| `GuestInteractionData` | `AnimalType`, `A_CanInteractWith` | `guestWalk` (`1` = true) |
| `SocialEnrichmentData` | `AnimalTypeA`, `AnimalTypeB` | `enrichedBy` (relationship stored once; expanded bidirectionally) |
| `AnimalBiomePreferences` | `AnimalType`, `BiomeName` | `biomes` (name-mapped, see below) |
| `AnimalContinentPreferences` | `AnimalType`, `ContinentName` | `continents` (name-mapped, see below) |

---

## `*zoopedia.fdb` — schema and field mapping

| Table | Relevant columns | → `animals.js` field |
|---|---|---|
| `BarrierRequirements` | `Species`, `Grade`, `MinHeight` | `barrier.grade` (int), `barrier.height` (float m) |

**Note:** This table is empty (0 rows) for Content17. Barnyard animal barrier data lives in the localisation OVL instead — see below.

---

## Localisation OVL files

Each content pack exposes display names, latin names, and barrier text via:

```
Content*/Localised/English/UnitedKingdom/Loc.ovl
```

After extraction, the relevant `.txt` files are keyed by `game_id.lower()` (e.g. `AlpineGoat` → `alpinegoat`). Game IDs are CamelCase with no underscores, which distinguishes them from plural/sign variants in the same archive.

| File pattern | Contains | → `animals.js` field |
|---|---|---|
| `animal_{gid}.txt` | Display name with correct punctuation (e.g. `Baird's Tapir`) | `name` |
| `zoopedia_scientificname_{gid}.txt` | Full latin binomial (e.g. `Tapirus bairdii`) | `latin` |
| `zoopedia_barrierrequirementsdescription_{gid}.txt` | Barrier text (e.g. `Grade 2  >1.25m`) | `barrier` (fallback when FDB is empty) |

**Barrier text format:** `Grade N  >X.XXm` (optionally `Grade N Climb Proof >X.XXm`).
Regex: `r'Grade\s+(\d+)(?:\s+Climb\s+Proof)?\s+>(\d+(?:\.\d+)?)m'`

The FDB `BarrierRequirements` table is the primary source for barrier data; the loc file is the fallback (authoritative for Content17 barnyard animals, whose FDB table is empty).

---

## Name mappings

The game FDB uses different identifiers than the app's JS arrays.

**Biomes** (`BIOME_NAME_MAP` in `extract_pz_data.py`):

| Game FDB value | App value |
|---|---|
| `Savannah` | `Grassland` |
| `Rainforest` | `Tropical` |
| `Tundra` | `Tundra` |
| `Taiga` | `Taiga` |
| `Temperate` | `Temperate` |
| `Desert` | `Desert` |
| `Aquatic` | `Aquatic` |

**Continents** (`CONTINENT_NAME_MAP` in `extract_pz_data.py`):

| Game FDB value | App value |
|---|---|
| `NorthAmerica` | `North America` |
| `SouthAmerica` | `South America` |
| `Australasia` | `Oceania` |
| `Europe` | `Europe` |
| `Asia` | `Asia` |
| `Africa` | `Africa` |
| `Arctic` | *(skipped — no app equivalent)* |
| `Antarctic` | *(skipped — no app equivalent)* |

---

## `img` filename convention

Portrait images live in `img/` and are named `<app_id>.png` where `app_id` is the animal's `id` field. The `img` field in `animals.js` always equals `id` — there is no separate naming scheme.

`app_id` is derived from the display name via `display_to_app_id()` in `extract_pz_data.py`: hyphens become underscores, apostrophes and accented characters are stripped, spaces become underscores, everything is lowercased.

To migrate existing images from the old `<latin_snake>.png` convention, run `rename_images.py`.

---

## Exhibit animals

Exhibit animals come from `*exhibits.fdb`. They have no terrain, barrier, or plant requirements. The script detects them by their presence in the exhibit database and absence from `AnimalTerrainRequirements`, and writes them with `exhibit: true` and full-range terrain placeholders (`[0,100]` for all types).

---

## Re-running the extraction

```
python extract_pz_data.py \
  --cobra-tools "path/to/cobra-tools-master" \
  --game-dir "C:/Program Files (x86)/Steam/steamapps/common/Planet Zoo"
```

No reference `animals.js` is needed — all data is read directly from game files. The existing `animals.js` (if present) is backed up to `animals.js.bak` before being overwritten. Pass `--no-cleanup` to keep the extracted FDB and TXT files for manual inspection.

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

| Table | Relevant columns | → output field |
|---|---|---|
| `AnimalTerrainRequirements` | `AnimalType`, `MinShortGrass`, `MaxShortGrass`, `MinLongGrass`, `MaxLongGrass`, `MinOverallSoil`, `MaxOverallSoil`, `MinOverallRock`, `MaxOverallRock`, `MinOverallSand`, `MaxOverallSand`, `MinSnow`, `MaxSnow` | `terrain.grassS/grassL/soil/rock/sand/snow` each as `[min, max]` |
| `AnimalHabitatRequirements` | `AnimalType`, `MinPlantCoverage`, `MaxPlantCoverage`, + temperature columns (see below) | `plants` as `[min, max]`; `tempMin`, `tempMax` (°C) |
| `SpaceRequirements` | `AnimalType`, `MinimumSpace`, + family group column (see below) | `landMin` (m²); `landMinGroup` (m²) |
| `AnimalDefinitions` | `AnimalType`, `ContentPack` | `pack` |
| `GuestInteractionData` | `AnimalType`, `A_CanInteractWith` | `guestWalk` (`1` = true) |
| `SocialEnrichmentData` | `AnimalTypeA`, `AnimalTypeB` | `enrichedBy` (relationship stored once; expanded bidirectionally) |
| `AnimalBiomePreferences` | `AnimalType`, `BiomeName` | `biomes` (name-mapped, see below) |
| `AnimalContinentPreferences` | `AnimalType`, `ContinentName` | `continents` (name-mapped, see below) |
| `DesiredPopulationSizes` | `AnimalType`, + min/max adults columns (see below) | `adultsMin`, `adultsMax` |
| `InterspeciesInteractionData` | `AnimalType`, + other-animal and interaction-type columns (see below) | `interspeciesInteractions` (raw rows in JSON) |
| `IdleBehaviourWeights` | `AnimalType`, `ActionWeightClimbing`, `ActionWeightInWater`, `ActionWeightDeepSwim`, `ActionWeightInBurrow` | `climber`, `canSwim`, `deepDiver`, `burrower` (boolean — true if any weight > 0 across any age/gender row) |
| `PounceVariablesData` | `AnimalType` (presence only) | `isPredator` (true if the animal has any pounce data) |

### Temperature columns in `AnimalHabitatRequirements`

**Confirmed from game files:** `MinComfortableTemperature` / `MaxComfortableTemperature`. Values are in °C as floats.

### Family group space — `SpaceRequirements`

There is no single "family group minimum space" column. The full confirmed schema is:

| Column | Type | → output field | Description |
|---|---|---|---|
| `MinimumSpace` | float (m²) | `landMin` | Minimum habitat space for 1 animal |
| `SpacePerAdditionalAnimal` | float (m²) | `spacePerAdditional` | Extra space per additional animal (adults and juveniles alike) |
| `MinimumAquaticSpace` | float (m²) | `aquaticMin` | Minimum aquatic area |
| `MinimumAquaticDepth` | float (m) | `aquaticDepth` | Minimum water depth |
| `AquaticSpacePerAdditionalAnimal` | float (m²) | `aquaticPerAdditional` | Extra aquatic area per additional animal |
| `MinimumClimbableSpace` | float (m²) | `climbMin` | Minimum climbable area |
| `ClimbableSpacePerAdditionalAnimal` | float (m²) | `climbPerAdditional` | Extra climbable area per additional animal |
| `MinimumDeepSwimmingSpace` | float (m²) | `deepSwimMin` | Minimum deep-swim area |
| `DeepSwimmingSpacePerAdditionalAnimal` | float (m²) | `deepSwimPerAdditional` | Extra deep-swim area per additional animal |
| `DeepSwimmingRequirementAffectsWelfare` | int (0/1) | `deepSwimAffectsWelfare` | Whether deep-swim shortage hurts welfare |
| `DoesJuvenileSwim` | int (0/1) | `juvenileSwims` | Juveniles use the aquatic space requirement |
| `DoesJuvenileDeepSwim` | int (0/1) | `juvenileDeepSwims` | Juveniles use the deep-swim space requirement |
| `MinimumShelterAreaPerAnimal` | float (m²) | `shelterMin` | Minimum shelter area per animal |

#### Family group space formula

`SpacePerAdditionalAnimal` applies to **every** additional animal including juveniles. The correct `landMinGroup` formula accounts for the maximum number of animals that can be simultaneously present — the maximum adult population plus the maximum simultaneous juvenile count:

```
landMinGroup = MinimumSpace + SpacePerAdditionalAnimal × (MaxPopulation + MaxFemalesBoth × MaxLitterSize − 1)
```

Where:
- `MaxPopulation` comes from `DesiredPopulationSizes`
- `MaxFemalesBoth` (max females in a mixed-sex group) comes from `DesiredGenderRatios`
- `MaxLitterSize` comes from `FertilityData`

**Validated example — Aardvark:**
`330 + 60 × (2 + 1×1 − 1) = 330 + 60×2 = 450 m²` ✓ (matches Villanelle's reference spreadsheet)

### Adults count columns in `DesiredPopulationSizes`

**Confirmed from game files:** `MinPopulation` (→ `adultsMin`) and `MaxPopulation` (→ `adultsMax`).

### `FertilityData` — litter size and reproduction timing

**Confirmed from game files.** One row per animal.

| Column | Type | → output field | Description |
|---|---|---|---|
| `AnimalType` | text | — | Game ID |
| `MinLitterSize` | int | `minLitterSize` | Minimum offspring per birth |
| `MaxLitterSize` | int | `maxLitterSize` | Maximum offspring per birth (used in `landMinGroup` formula) |
| `GestationTime` | float (days) | `gestationTime` | In-game days from conception to birth |
| `InterBirthTime` | float (days) | `interBirthTime` | Minimum in-game days between births |
| `FertilityValue` | float | — | Not extracted |
| `InfertileAge` | float | — | Not extracted |
| `ZoopediaReproduction` | text | — | Loc key for zoopedia text |

### `DesiredGenderRatios` — group composition limits

**Confirmed from game files.** One row per animal.

| Column | Type | → output field | Description |
|---|---|---|---|
| `AnimalType` | text | — | Game ID |
| `MaxMalesSingle` | int | `maxMalesSingle` | Max males in a single-sex (male-only) group |
| `MaxFemalesSingle` | int | `maxFemalesSingle` | Max females in a single-sex (female-only) group |
| `MaxMalesBoth` | int | `maxMalesBoth` | Max males in a mixed-sex group |
| `MaxFemalesBoth` | int | `maxFemalesBoth` | Max females in a mixed-sex group (used in `landMinGroup` formula) |
| `DesiredRatio` | float | — | Not extracted |
| `DominantSex` | text | — | Not extracted |

The maximum mixed-sex adult count = `MaxMalesBoth + MaxFemalesBoth`, which equals `MaxPopulation` from `DesiredPopulationSizes`.

### `InterspeciesInteractionData` — predation profile (per-animal, not per-pair)

**Confirmed from game files.** Despite its name, this table has **one row per animal**, not one row per animal pair. It describes each animal's role in the food chain:

| Column | Values | Description |
|---|---|---|
| `PredatorPrey` | `'Predator'` / `'Prey'` | Whether this animal is a predator or prey |
| `AdultTrophicLevel` | `'Level00'`–`'Level30'`, `'LevelApex'` | Adult trophic level; a predator can only kill prey with a numerically lower level |
| `JuvenileTrophicLevel` | same scale | Trophic level of juveniles |
| `Temperament` | `'Passive'` / `'Aggressive'` | Affects behaviour in mixed habitats |
| `HasDefensiveIntimidate` | `0` / `1` | Animal can actively intimidate predators away |
| `DefensiveIntimidationStartRadius` | float (m) | Radius at which intimidation begins |
| `DefensiveIntimidationEndRadius` | float (m) | Radius at which intimidation ends |
| `DefensiveIntimidationGimmickRadius` | float (m) | Gimmick animation trigger radius |

**`LevelApex`** = the animal cannot be killed by any predator regardless of the predator's level. Confirmed apex-level animals: Aldabra Giant Tortoise, African Spurred Tortoise, Galápagos Giant Tortoise.

**Rhino/hippo compatibility:** Both species have `AdultTrophicLevel = Level27` and `Temperament = Aggressive`. The game uses this combination to determine fighting/dominance conflicts between animals of the same high trophic tier.

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

**Note:** Exhibit animals have a separate temperature table (`ExhibitAnimalTemperatureData` in `*exhibits.fdb`) which is not currently queried.

---

## Extracted fields reference

All fields below are present in the JSON output for all habitat animals. Fields marked `null` were not found in the game files for that animal.

### Space fields

| Field | Type | Source table | Description |
|---|---|---|---|
| `landMin` | `number` | `SpaceRequirements` | Minimum habitat land area for 1 animal (m²) |
| `landMinGroup` | `number \| null` | Derived | Habitat area for maximum group including juveniles (m²); see formula above |
| `spacePerAdditional` | `number \| null` | `SpaceRequirements` | Extra m² per additional animal (adults and juveniles) |
| `aquaticMin` | `number \| null` | `SpaceRequirements` | Minimum aquatic area (m²) |
| `aquaticPerAdditional` | `number \| null` | `SpaceRequirements` | Extra aquatic area per additional animal (m²) |
| `aquaticDepth` | `number \| null` | `SpaceRequirements` | Minimum water depth (m) |
| `climbMin` | `number \| null` | `SpaceRequirements` | Minimum climbable area (m²) |
| `climbPerAdditional` | `number \| null` | `SpaceRequirements` | Extra climbable area per additional animal (m²) |
| `deepSwimMin` | `number \| null` | `SpaceRequirements` | Minimum deep-swim area (m²) |
| `deepSwimPerAdditional` | `number \| null` | `SpaceRequirements` | Extra deep-swim area per additional animal (m²) |
| `shelterMin` | `number \| null` | `SpaceRequirements` | Minimum shelter area per animal (m²) |

### Climate and habitat fields

| Field | Type | Source table | Description |
|---|---|---|---|
| `tempMin` | `number \| null` | `AnimalHabitatRequirements` | Comfortable temperature lower bound (°C) |
| `tempMax` | `number \| null` | `AnimalHabitatRequirements` | Comfortable temperature upper bound (°C) |

### Population and group composition fields

| Field | Type | Source table | Description |
|---|---|---|---|
| `adultsMin` | `number \| null` | `DesiredPopulationSizes` | Minimum adults in family group |
| `adultsMax` | `number \| null` | `DesiredPopulationSizes` | Maximum adults in family group |
| `maxMalesSingle` | `number \| null` | `DesiredGenderRatios` | Max males in a single-sex (male-only) group |
| `maxFemalesSingle` | `number \| null` | `DesiredGenderRatios` | Max females in a single-sex (female-only) group |
| `maxMalesBoth` | `number \| null` | `DesiredGenderRatios` | Max males in a mixed-sex group |
| `maxFemalesBoth` | `number \| null` | `DesiredGenderRatios` | Max females in a mixed-sex group |

### Fertility fields

| Field | Type | Source table | Description |
|---|---|---|---|
| `minLitterSize` | `number \| null` | `FertilityData` | Minimum offspring per birth |
| `maxLitterSize` | `number \| null` | `FertilityData` | Maximum offspring per birth |
| `gestationTime` | `number \| null` | `FertilityData` | In-game days from conception to birth |
| `interBirthTime` | `number \| null` | `FertilityData` | Minimum in-game days between births |

### Behaviour flags

| Field | Type | Source table | Description |
|---|---|---|---|
| `climber` | `boolean` | `IdleBehaviourWeights` | True if `ActionWeightClimbing > 0` for any row |
| `canSwim` | `boolean` | `IdleBehaviourWeights` | True if `ActionWeightInWater > 0` for any row |
| `deepDiver` | `boolean` | `IdleBehaviourWeights` | True if `ActionWeightDeepSwim > 0` for any row |
| `burrower` | `boolean` | `IdleBehaviourWeights` | True if `ActionWeightInBurrow > 0` for any row |

### Predation fields

| Field | Type | Source table | Description |
|---|---|---|---|
| `isPredator` | `boolean` | Derived | `true` when `predatorPrey === 'Predator'` |
| `predatorPrey` | `'Predator'\|'Prey'` | `InterspeciesInteractionData` | Role in food chain |
| `adultTrophicLevel` | `string` | `InterspeciesInteractionData` | e.g. `'Level15'`, `'LevelApex'` |
| `juvenileTrophicLevel` | `string` | `InterspeciesInteractionData` | Juvenile trophic level |
| `temperament` | `'Passive'\|'Aggressive'` | `InterspeciesInteractionData` | Affects inter-species conflict |
| `wellDefended` | `boolean` | Derived | `true` when `adultTrophicLevel === 'LevelApex'` — cannot be killed by any predator |
| `hasDefensiveIntimidate` | `boolean` | `InterspeciesInteractionData` | Can intimidate predators away |

### Notes on derived fields

- **`landMinGroup`** = `landMin + spacePerAdditional × (adultsMax + maxFemalesBoth × maxLitterSize − 1)`. Juveniles count as occupants — every female can simultaneously have a full litter.
- **`wellDefended`** is `true` for exactly 3 animals: Aldabra Giant Tortoise, African Spurred Tortoise, Galápagos Giant Tortoise.
- **Predator compatibility**: a predator with `AdultTrophicLevel = LevelN` will kill prey whose `AdultTrophicLevel` is numerically lower than N, unless the prey is `LevelApex` or has `HasDefensiveIntimidate = 1`.
- **Rhino/hippo aggression**: Black Rhinoceros, Southern White Rhinoceros, and Hippopotamus all share `AdultTrophicLevel = Level27` and `Temperament = Aggressive`. The game uses this combination to trigger dominance conflicts between animals of the same high trophic tier in the same habitat.

---

## Re-running the extraction

```
python extract_pz_data.py \
  --cobra-tools "path/to/cobra-tools-master" \
  --game-dir "C:/Program Files (x86)/Steam/steamapps/common/Planet Zoo"
```

No reference `animals.js` is needed — all data is read directly from game files. The existing `animals.js` (if present) is backed up to `animals.js.bak` before being overwritten. Pass `--no-cleanup` to keep the extracted FDB and TXT files for manual inspection.

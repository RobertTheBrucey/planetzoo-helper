#!/usr/bin/env python3
"""
Extract Planet Zoo animal habitat data from game OVL files using cobra-tools.

For each habitat animal found, outputs:
  terrain slider ranges (grassS, grassL, soil, rock, sand, snow)
  plant coverage range
  minimum enclosure land area (individual and family group)
  comfortable temperature range (°C)
  adults in family group (min/max)
  barrier grade and height
  enrichedBy partner names
  guestWalk flag
  latin (scientific) name
  display name (with correct punctuation)
  biomes and continents
  behaviour flags (climber, canSwim, deepDiver, burrower)
  isPredator flag (animals with pounce/predation data)
  interspecies interaction data (predator/prey/compatibility raw rows)

All data is extracted directly from game files — no reference animals.js needed.

Usage:
  python extract_pz_data.py \\
      --cobra-tools "C:/path/to/cobra-tools-master" \\
      --game-dir "C:/Program Files (x86)/Steam/steamapps/common/Planet Zoo" \\
      [--output extracted_animals.json] \\
      [--js-output animals.js] \\
      [--extract-dir /tmp/pz_extract] \\
      [--no-cleanup]
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Content pack number → short display name used in the app.
# Add entries here as new DLCs release.
# ---------------------------------------------------------------------------
CONTENT_PACK_NAMES = {
    "BaseGame":        "Standard",
    "Deluxe":          "Deluxe",
    "Content1":        "Arid",
    "Content2":        "Africa",
    "Content3":        "North America",
    "Content4":        "Arctic",
    "Content5":        "South America",
    "Content6":        "Southeast Asia",
    "Content7":        "Australia",
    "Content8":        "Conservation",
    "Content9":        "Wetlands",
    "Content10":       "Europe",
    "Content11":       "Eurasia",
    "Content12":       "Grasslands",
    "Content13":       "Tropical",
    "Content14":       "Oceania",
    "Content15":       "Twilight",
    "Content16":       "Eurasia",
    "Content17":       "Barnyard",
    "Content18":       "Zookeepers",
    "Content19":       "Americas",
    "Content20":       "Asia",
    "ContentAnniversary":  "Anniversary",
    "ContentAnniversary2": "Anniversary",
    "ContentAnniversary3": "Anniversary",
}

# ---------------------------------------------------------------------------
# Game identifier → app display name mappings.
# The game's FDB files use different names than the app's JS arrays.
# ---------------------------------------------------------------------------
BIOME_NAME_MAP = {
    "Savannah":  "Grassland",
    "Rainforest": "Tropical",
    "Tundra":    "Tundra",
    "Taiga":     "Taiga",
    "Temperate": "Temperate",
    "Desert":    "Desert",
    "Aquatic":   "Aquatic",
}

CONTINENT_NAME_MAP = {
    "Europe":       "Europe",
    "Asia":         "Asia",
    "Africa":       "Africa",
    "NorthAmerica": "North America",
    "SouthAmerica": "South America",
    "Australasia":  "Oceania",
    # Arctic and Antarctic have no app equivalent — skip them
}


def camel_to_display(name: str) -> str:
    """Convert CamelCase game ID to a display name: 'SnowLeopard' → 'Snow Leopard'."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    # Handle sequences like 'IDs', 'BW', etc.
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return spaced.strip()


def find_content_dirs(game_dir: Path) -> list[Path]:
    """Return all Content* OVL data directories, sorted."""
    ovl_root = game_dir / "win64" / "ovldata"
    if not ovl_root.exists():
        sys.exit(f"ERROR: ovldata not found at {ovl_root}")
    dirs = sorted(
        p for p in ovl_root.iterdir()
        if p.is_dir() and p.name.startswith("Content")
    )
    return dirs


def _run_cobra_extract(cobra_tools: Path, ovl_path: Path, out_dir: Path) -> subprocess.CompletedProcess:
    out_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(cobra_tools / "ovl_tool_cmd.py"), "extract",
         "--game", "Planet Zoo", "--output", str(out_dir), str(ovl_path)],
        capture_output=True, text=True, cwd=str(cobra_tools),
    )


def extract_fdb_files(cobra_tools: Path, ovl_path: Path, out_dir: Path) -> list[Path]:
    """
    Extract all .fdb files from a single OVL using cobra-tools.
    Returns list of extracted .fdb paths.
    """
    result = _run_cobra_extract(cobra_tools, ovl_path, out_dir)
    if "SUCCESS | Extracting" not in result.stdout:
        if "SUCCESS" not in result.stdout:
            print(f"  WARNING: cobra-tools output for {ovl_path.name}:")
            for line in result.stdout.splitlines()[-5:]:
                print(f"    {line}")
    return list(out_dir.glob("*.fdb"))


def find_loc_ovl(content_dir: Path) -> Path | None:
    """Return path to the English localisation OVL for a content pack, or None."""
    p = content_dir / "Localised" / "English" / "UnitedKingdom" / "Loc.ovl"
    return p if p.exists() else None


def extract_loc_files(cobra_tools: Path, loc_ovl: Path, out_dir: Path) -> None:
    """Extract Loc.ovl txt files into out_dir."""
    result = _run_cobra_extract(cobra_tools, loc_ovl, out_dir)
    if "SUCCESS" not in result.stdout:
        print(f"  WARNING: loc extraction may have failed for {loc_ovl}")


def parse_loc_data(loc_dir: Path) -> dict:
    """
    Scan extracted localisation txt files and return data keyed by game_id_lower.

    Collects:
      name   — from animal_{gid}.txt (display name with correct punctuation)
      latin  — from zoopedia_scientificname_{gid}.txt
      barrier — from zoopedia_barrierrequirementsdescription_{gid}.txt

    game_id_lower is game_id.lower() with no other transformation, e.g.
    AlpineGoat → alpinegoat.  Animal name files (not plural/sign variants) have
    no underscore in the part after "animal_", which is how they are filtered.
    """
    result: dict[str, dict] = {}

    for txt in loc_dir.glob("*.txt"):
        stem = txt.stem
        try:
            content = txt.read_text(encoding="utf-8").strip()
        except OSError:
            continue

        if stem.startswith("animal_"):
            gid_lower = stem[len("animal_"):]
            # Game IDs are CamelCase so game_id.lower() has no underscores.
            # Plural/sign/food variants all contain an underscore — skip them.
            if "_" in gid_lower:
                continue
            result.setdefault(gid_lower, {})["name"] = content

        elif stem.startswith("zoopedia_scientificname_"):
            gid_lower = stem[len("zoopedia_scientificname_"):]
            result.setdefault(gid_lower, {})["latin"] = content

        elif stem.startswith("zoopedia_barrierrequirementsdescription_"):
            gid_lower = stem[len("zoopedia_barrierrequirementsdescription_"):]
            m = re.search(
                r'Grade\s+(\d+)(?:\s+Climb\s+Proof)?\s+>(\d+(?:\.\d+)?)m',
                content, re.IGNORECASE,
            )
            if m:
                result.setdefault(gid_lower, {})["barrier"] = {
                    "grade":  int(m.group(1)),
                    "height": float(m.group(2)),
                }

    return result


def open_db(path: Path) -> sqlite3.Connection | None:
    """Open a SQLite database, returning None if it fails."""
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"  WARNING: Cannot open {path.name}: {e}")
        return None


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set:
    """Return set of column names for a table (empty set if table does not exist)."""
    if not table_exists(conn, table_name):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


# ---------------------------------------------------------------------------
# Per-database queries
# ---------------------------------------------------------------------------

def query_terrain(conn: sqlite3.Connection) -> dict:
    """AnimalTerrainRequirements → terrain ranges (0–100 %)."""
    if not table_exists(conn, "AnimalTerrainRequirements"):
        return {}
    out = {}
    for row in conn.execute("SELECT * FROM AnimalTerrainRequirements"):
        d = dict(row)
        animal = d["AnimalType"]
        def pct(v):
            return round(v * 100) if v is not None else 0
        out[animal] = {
            "grassS": [pct(d["MinShortGrass"]), pct(d["MaxShortGrass"])],
            "grassL": [pct(d["MinLongGrass"]),  pct(d["MaxLongGrass"])],
            "soil":   [pct(d["MinOverallSoil"]), pct(d["MaxOverallSoil"])],
            "rock":   [pct(d["MinOverallRock"]), pct(d["MaxOverallRock"])],
            "sand":   [pct(d["MinOverallSand"]), pct(d["MaxOverallSand"])],
            "snow":   [pct(d["MinSnow"]),         pct(d["MaxSnow"])],
        }
    return out


def query_habitat(conn: sqlite3.Connection) -> dict:
    """
    AnimalHabitatRequirements → plant coverage (0–100 %) and temperature range (°C).

    Temperature columns are discovered at runtime — several naming conventions are
    tried.  If none match, the known column names are printed so they can be added.
    """
    if not table_exists(conn, "AnimalHabitatRequirements"):
        return {}
    cols = get_table_columns(conn, "AnimalHabitatRequirements")

    # Try candidate pairs in order of likelihood.
    temp_pair: tuple[str, str] | None = None
    for mn, mx in [
        ("MinComfortableTemperature", "MaxComfortableTemperature"),
        ("MinTemperature", "MaxTemperature"),
        ("ComfortableTemperatureMin", "ComfortableTemperatureMax"),
        ("TempMin", "TempMax"),
        ("MinTemp", "MaxTemp"),
    ]:
        if mn in cols and mx in cols:
            temp_pair = (mn, mx)
            break

    unknown = cols - {"AnimalType", "MinPlantCoverage", "MaxPlantCoverage"}
    if temp_pair is None and unknown:
        print(f"  NOTE: AnimalHabitatRequirements extra columns (no temp found): {sorted(unknown)}")

    out = {}
    for row in conn.execute("SELECT * FROM AnimalHabitatRequirements"):
        d = dict(row)
        animal = d["AnimalType"]
        entry: dict = {
            "plants": [
                round((d.get("MinPlantCoverage") or 0) * 100),
                round((d.get("MaxPlantCoverage") or 0) * 100),
            ]
        }
        if temp_pair:
            t_min = d.get(temp_pair[0])
            t_max = d.get(temp_pair[1])
            if t_min is not None:
                entry["tempMin"] = round(float(t_min), 1)
            if t_max is not None:
                entry["tempMax"] = round(float(t_max), 1)
        out[animal] = entry
    return out


def query_space(conn: sqlite3.Connection) -> dict:
    """
    SpaceRequirements → per-individual minimum land area and (if present)
    family-group minimum land area, both in m².

    Returns dict of animalType → {landMin, landMinGroup?}.
    """
    if not table_exists(conn, "SpaceRequirements"):
        return {}
    cols = get_table_columns(conn, "SpaceRequirements")

    _known_space_cols = {
        "AnimalType", "MinimumSpace", "SpacePerAdditionalAnimal",
        "MinimumAquaticSpace", "MinimumAquaticDepth", "AquaticSpacePerAdditionalAnimal",
        "MinimumClimbableSpace", "ClimbableSpacePerAdditionalAnimal",
        "MinimumDeepSwimmingSpace", "DeepSwimmingSpacePerAdditionalAnimal",
        "DeepSwimmingRequirementAffectsWelfare", "DoesJuvenileSwim", "DoesJuvenileDeepSwim",
        "MinimumShelterAreaPerAnimal",
    }
    unknown = cols - _known_space_cols
    if unknown:
        print(f"  NOTE: SpaceRequirements unknown columns: {sorted(unknown)}")

    out = {}
    for row in conn.execute("SELECT * FROM SpaceRequirements"):
        d = dict(row)
        animal = d["AnimalType"]
        if d.get("MinimumSpace") is None:
            continue
        entry: dict = {"landMin": int(round(d["MinimumSpace"]))}
        _space_cols: list[tuple] = [
            ("SpacePerAdditionalAnimal",             "spacePerAdditional",        lambda v: int(round(v))),
            ("MinimumAquaticSpace",                  "aquaticMin",                lambda v: int(round(v))),
            ("MinimumAquaticDepth",                  "aquaticDepth",              lambda v: round(float(v), 2)),
            ("AquaticSpacePerAdditionalAnimal",      "aquaticPerAdditional",      lambda v: int(round(v))),
            ("MinimumClimbableSpace",                "climbMin",                  lambda v: int(round(v))),
            ("ClimbableSpacePerAdditionalAnimal",    "climbPerAdditional",        lambda v: int(round(v))),
            ("MinimumDeepSwimmingSpace",             "deepSwimMin",               lambda v: int(round(v))),
            ("DeepSwimmingSpacePerAdditionalAnimal", "deepSwimPerAdditional",     lambda v: int(round(v))),
            ("DeepSwimmingRequirementAffectsWelfare","deepSwimAffectsWelfare",    bool),
            ("DoesJuvenileSwim",                     "juvenileSwims",             bool),
            ("DoesJuvenileDeepSwim",                 "juvenileDeepSwims",         bool),
            ("MinimumShelterAreaPerAnimal",          "shelterMin",                lambda v: int(round(v))),
        ]
        for col, key, transform in _space_cols:
            if col in cols and d.get(col) is not None:
                entry[key] = transform(d[col])
        out[animal] = entry
    return out


def query_definitions(conn: sqlite3.Connection) -> dict:
    """AnimalDefinitions → content pack tag per animal."""
    if not table_exists(conn, "AnimalDefinitions"):
        return {}
    return {
        row["AnimalType"]: row["ContentPack"]
        for row in conn.execute("SELECT AnimalType, ContentPack FROM AnimalDefinitions")
        if row["ContentPack"]
    }


def query_guest_walk(conn: sqlite3.Connection) -> set:
    """GuestInteractionData → set of animals with guestWalk=true."""
    if not table_exists(conn, "GuestInteractionData"):
        return set()
    return {
        row["AnimalType"]
        for row in conn.execute(
            "SELECT AnimalType, A_CanInteractWith FROM GuestInteractionData"
            " WHERE A_CanInteractWith = 1"
        )
    }


def query_enrichment(conn: sqlite3.Connection) -> dict:
    """
    SocialEnrichmentData → dict of animal → set of enrichment partners.
    Relationship is stored once per pair; we expand bidirectionally.
    """
    if not table_exists(conn, "SocialEnrichmentData"):
        return {}
    pairs: list[tuple[str, str]] = [
        (row["AnimalTypeA"], row["AnimalTypeB"])
        for row in conn.execute(
            "SELECT AnimalTypeA, AnimalTypeB FROM SocialEnrichmentData"
        )
    ]
    result: dict[str, set] = {}
    for a, b in pairs:
        result.setdefault(a, set()).add(b)
        result.setdefault(b, set()).add(a)
    return result


def query_barrier(conn: sqlite3.Connection) -> dict:
    """BarrierRequirements (in zoopedia db) → barrier grade and height."""
    if not table_exists(conn, "BarrierRequirements"):
        return {}
    out = {}
    for row in conn.execute(
        "SELECT Species, Grade, MinHeight FROM BarrierRequirements WHERE Grade IS NOT NULL"
    ):
        out[row["Species"]] = {
            "grade":  int(row["Grade"]),
            "height": float(row["MinHeight"]),
        }
    return out


def query_biome_prefs(conn: sqlite3.Connection) -> dict:
    """AnimalBiomePreferences → dict of game_id → list of app biome names."""
    if not table_exists(conn, "AnimalBiomePreferences"):
        return {}
    out: dict[str, list] = {}
    for row in conn.execute("SELECT AnimalType, BiomeName FROM AnimalBiomePreferences"):
        mapped = BIOME_NAME_MAP.get(row["BiomeName"])
        if mapped:
            out.setdefault(row["AnimalType"], []).append(mapped)
    return out


def query_continent_prefs(conn: sqlite3.Connection) -> dict:
    """AnimalContinentPreferences → dict of game_id → list of app continent names."""
    if not table_exists(conn, "AnimalContinentPreferences"):
        return {}
    out: dict[str, list] = {}
    for row in conn.execute("SELECT AnimalType, ContinentName FROM AnimalContinentPreferences"):
        mapped = CONTINENT_NAME_MAP.get(row["ContinentName"])
        if mapped:
            out.setdefault(row["AnimalType"], []).append(mapped)
    return out


def query_population(conn: sqlite3.Connection) -> dict:
    """
    DesiredPopulationSizes → adults min/max per animal (family group size).

    Actual columns confirmed from game files: MinPopulation, MaxPopulation.
    """
    if not table_exists(conn, "DesiredPopulationSizes"):
        return {}
    cols = get_table_columns(conn, "DesiredPopulationSizes")

    min_col: str | None = next(
        (c for c in (
            "MinPopulation", "MinAdults", "MinimumAdults", "DesiredMinAdults",
            "MinDesiredAdults", "MinGroupSize", "MinimumGroupSize", "MinMembers",
        ) if c in cols),
        None,
    )
    max_col: str | None = next(
        (c for c in (
            "MaxPopulation", "MaxAdults", "MaximumAdults", "DesiredMaxAdults",
            "MaxDesiredAdults", "MaxGroupSize", "MaximumGroupSize", "MaxMembers",
        ) if c in cols),
        None,
    )
    if min_col is None or max_col is None:
        print(f"  NOTE: DesiredPopulationSizes columns (unmatched): {sorted(cols)}")

    out = {}
    for row in conn.execute("SELECT * FROM DesiredPopulationSizes"):
        d = dict(row)
        animal = d["AnimalType"]
        entry: dict = {}
        if min_col and d.get(min_col) is not None:
            entry["adultsMin"] = int(d[min_col])
        if max_col and d.get(max_col) is not None:
            entry["adultsMax"] = int(d[max_col])
        if entry:
            out[animal] = entry
    return out


def query_fertility(conn: sqlite3.Connection) -> dict:
    """
    FertilityData → litter size range and reproduction timing per animal.

    Confirmed columns: AnimalType, MinLitterSize, MaxLitterSize, GestationTime,
    InterBirthTime, FertilityValue, InfertileAge, ZoopediaReproduction.
    GestationTime and InterBirthTime are in in-game days.
    """
    if not table_exists(conn, "FertilityData"):
        return {}
    cols = get_table_columns(conn, "FertilityData")
    out = {}
    for row in conn.execute("SELECT * FROM FertilityData"):
        d = dict(row)
        animal = d["AnimalType"]
        entry: dict = {}
        for col, key, fn in [
            ("MinLitterSize",  "minLitterSize",  lambda v: int(v)),
            ("MaxLitterSize",  "maxLitterSize",  lambda v: int(v)),
            ("GestationTime",  "gestationTime",  lambda v: int(round(v))),
            ("InterBirthTime", "interBirthTime", lambda v: int(round(v))),
        ]:
            if col in cols and d.get(col) is not None:
                entry[key] = fn(d[col])
        if entry:
            out[animal] = entry
    return out


def query_gender_ratios(conn: sqlite3.Connection) -> dict:
    """
    DesiredGenderRatios → group composition limits per animal.

    Confirmed columns: AnimalType, MaxMalesSingle, MaxFemalesSingle,
    MaxMalesBoth, MaxFemalesBoth, DesiredRatio, DominantSex.

    *Single = max of that sex in a single-sex group.
    *Both = max of that sex in a mixed-sex group.
    MaxFemalesBoth is used with MaxLitterSize to compute the max juvenile
    count when deriving the correct landMinGroup.
    """
    if not table_exists(conn, "DesiredGenderRatios"):
        return {}
    cols = get_table_columns(conn, "DesiredGenderRatios")
    out = {}
    for row in conn.execute("SELECT * FROM DesiredGenderRatios"):
        d = dict(row)
        animal = d["AnimalType"]
        entry: dict = {}
        for col, key in [
            ("MaxMalesSingle",   "maxMalesSingle"),
            ("MaxFemalesSingle", "maxFemalesSingle"),
            ("MaxMalesBoth",     "maxMalesBoth"),
            ("MaxFemalesBoth",   "maxFemalesBoth"),
        ]:
            if col in cols and d.get(col) is not None:
                entry[key] = int(d[col])
        if entry:
            out[animal] = entry
    return out


def query_predation_profile(conn: sqlite3.Connection) -> dict:
    """
    InterspeciesInteractionData → per-animal predation profile.

    Despite its name this table is NOT a pair table — it has one row per animal
    describing its role in the food chain.  Actual columns confirmed from game files:

      PredatorPrey            — 'Predator' or 'Prey'
      AdultTrophicLevel       — 'Level00'…'Level30', 'LevelApex'
      JuvenileTrophicLevel    — same scale
      Temperament             — 'Passive' or 'Aggressive'
      HasDefensiveIntimidate  — 0/1; animal can intimidate predators away
      DefensiveIntimidationStartRadius / EndRadius / GimmickRadius — radii (m)

    A predator can eat any Prey animal whose AdultTrophicLevel is numerically lower
    than the predator's own AdultTrophicLevel.  'LevelApex' prey cannot be killed
    by any predator (e.g. Aldabra Giant Tortoise, African Spurred Tortoise).

    Returns dict of animalType → profile dict.
    """
    if not table_exists(conn, "InterspeciesInteractionData"):
        return {}

    out: dict[str, dict] = {}
    try:
        for row in conn.execute(
            "SELECT AnimalType, PredatorPrey, AdultTrophicLevel, JuvenileTrophicLevel,"
            " Temperament, HasDefensiveIntimidate,"
            " DefensiveIntimidationStartRadius, DefensiveIntimidationEndRadius,"
            " DefensiveIntimidationGimmickRadius"
            " FROM InterspeciesInteractionData"
        ):
            d = dict(row)
            animal = d["AnimalType"]
            out[animal] = {
                "predatorPrey":             d.get("PredatorPrey", ""),
                "adultTrophicLevel":        d.get("AdultTrophicLevel", ""),
                "juvenileTrophicLevel":     d.get("JuvenileTrophicLevel", ""),
                "temperament":              d.get("Temperament", ""),
                "hasDefensiveIntimidate":   bool(d.get("HasDefensiveIntimidate", 0)),
                "defensiveIntimidationRadius": d.get("DefensiveIntimidationStartRadius"),
            }
    except sqlite3.OperationalError as exc:
        cols = get_table_columns(conn, "InterspeciesInteractionData")
        print(f"  NOTE: InterspeciesInteractionData query error: {exc}")
        print(f"  Actual columns: {sorted(cols)}")
    return out


def query_behaviors(conn: sqlite3.Connection) -> dict:
    """
    IdleBehaviourWeights → climber / canSwim / deepDiver / burrower flags.

    A flag is set True if any row for that animal has the relevant action
    weight > 0 (across any age group / gender combination).
    """
    if not table_exists(conn, "IdleBehaviourWeights"):
        return {}
    out: dict[str, dict] = {}
    try:
        for row in conn.execute(
            "SELECT AnimalType, ActionWeightClimbing, ActionWeightInWater,"
            " ActionWeightDeepSwim, ActionWeightInBurrow FROM IdleBehaviourWeights"
        ):
            animal = row["AnimalType"]
            e = out.setdefault(animal, {
                "climber": False, "canSwim": False,
                "deepDiver": False, "burrower": False,
            })
            if (row["ActionWeightClimbing"] or 0) > 0:
                e["climber"]   = True
            if (row["ActionWeightInWater"] or 0) > 0:
                e["canSwim"]   = True
            if (row["ActionWeightDeepSwim"] or 0) > 0:
                e["deepDiver"] = True
            if (row["ActionWeightInBurrow"] or 0) > 0:
                e["burrower"]  = True
    except sqlite3.OperationalError as exc:
        print(f"  NOTE: IdleBehaviourWeights query error: {exc}")
    return out


def query_predators(conn: sqlite3.Connection) -> set:
    """
    PounceVariablesData → set of animals that can pounce (predators).

    Any animal with rows in PounceVariablesData is treated as a predator.
    """
    if not table_exists(conn, "PounceVariablesData"):
        return set()
    return {
        row[0]
        for row in conn.execute("SELECT DISTINCT AnimalType FROM PounceVariablesData")
    }


def query_exhibits(conn: sqlite3.Connection) -> set:
    """Return set of animal types that are exhibits (from *exhibits.fdb)."""
    for table in ("ExhibitAnimalDefinitions", "AnimalDefinitions", "SpeciesEnum"):
        if table_exists(conn, table):
            try:
                rows = conn.execute(f"SELECT * FROM {table} LIMIT 0").description
                cols = [r[0] for r in rows]
                type_col = next(
                    (c for c in cols if "animal" in c.lower() or "species" in c.lower() or "type" in c.lower()),
                    cols[0] if cols else None,
                )
                if type_col:
                    return {
                        row[0]
                        for row in conn.execute(f"SELECT {type_col} FROM {table}")
                    }
            except sqlite3.Error:
                continue
    return set()


# ---------------------------------------------------------------------------
# Committed-data helpers (used by rename_images.py; kept for import)
# ---------------------------------------------------------------------------

def build_committed_map(animals_js: Path) -> dict[str, dict]:
    """
    Parse animals.js and return a merged lookup keyed by app_id and guessed game_id.
    Used by rename_images.py to build the old→new image rename mapping.
    """
    if not animals_js.exists():
        return {}
    text = animals_js.read_text(encoding="utf-8")
    result: dict[str, dict] = {}
    for line in text.splitlines():
        m = re.search(r"\{id:'([^']+)',name:('(?:[^']+)'|\"(?:[^\"]+)\")", line)
        if not m:
            continue
        app_id = m.group(1)
        name   = m.group(2).strip("'\"")

        latin_m = re.search(r"latin:'([^']*)'", line)
        latin   = latin_m.group(1) if latin_m else ""

        pack_m = re.search(r"pack:'([^']*)'", line)
        c_pack = pack_m.group(1) if pack_m else ""

        img_m = re.search(r"img:'([^']*)'", line)
        img   = img_m.group(1) if img_m else ""

        cont_m     = re.search(r"continents:(\[[^\]]*\])", line)
        continents = re.findall(r"'([^']+)'", cont_m.group(1)) if cont_m else []

        biomes_m = re.search(r"biomes:(\[[^\]]*\])", line)
        biomes   = re.findall(r"'([^']+)'", biomes_m.group(1)) if biomes_m else []

        entry = {
            "app_id":     app_id,
            "name":       name,
            "latin":      latin,
            "pack":       c_pack,
            "continents": continents,
            "biomes":     biomes,
            "img":        img,
        }
        result[app_id] = entry
        game_id_guess = "".join(w.capitalize() for w in app_id.split("_"))
        result[game_id_guess] = entry

    return result


def display_to_app_id(display_name: str) -> str:
    """Convert display name to snake_case app id: 'Snow Leopard' -> 'snow_leopard'."""
    clean = display_name.replace("-", " ")          # hyphens become underscores
    clean = re.sub(r"[^a-zA-Z0-9 ]", "", clean)    # strip apostrophes, accents, etc.
    return "_".join(clean.lower().split())


def game_id_to_display(game_id: str, loc_map: dict) -> str:
    """Return display name for a game ID using loc data, falling back to auto-generated."""
    loc = loc_map.get(game_id.lower(), {})
    if loc.get("name"):
        return loc["name"]
    return camel_to_display(game_id)


# ---------------------------------------------------------------------------
# JS formatting
# ---------------------------------------------------------------------------

def format_js_entry(animal: dict, loc_map: dict) -> str:
    """Format one animal dict as a single-line JS object matching the app format."""
    game_id = animal["game_id"]
    gid_lower = game_id.lower()
    loc = loc_map.get(gid_lower, {})

    # Display name: loc file preserves apostrophes, hyphens, etc.
    name   = loc.get("name") or camel_to_display(game_id)
    app_id = display_to_app_id(name)
    pack   = animal.get("pack", "Unknown")
    exhibit = animal.get("exhibit", False)
    guest   = animal.get("guestWalk", False)

    # All these fields come from game files — no committed reference needed.
    latin = loc.get("latin", "")
    img   = app_id  # img filename always equals the app id

    biomes     = sorted(animal.get("biomes_from_game", []))
    continents = sorted(animal.get("continents_from_game", []))

    # Barrier: FDB BarrierRequirements first (most packs), loc text fallback (e.g. Content17).
    bar = animal.get("barrier") or {}
    if not bar.get("grade") and loc.get("barrier"):
        bar = loc["barrier"]

    # enrichedBy: convert game IDs to display names using loc data
    raw_enriched   = sorted(animal.get("enrichedBy", []))
    enriched_names = [game_id_to_display(e, loc_map) for e in raw_enriched]

    def js_str(s: str) -> str:
        return f'"{s}"' if "'" in s else f"'{s}'"

    enriched_js = "[" + ",".join(js_str(n) for n in enriched_names) + "]"
    conts_js    = "[" + ",".join(f"'{c}'" for c in continents) + "]"
    biomes_js   = "[" + ",".join(f"'{b}'" for b in biomes) + "]"

    def rng(pair: list) -> str:
        return f"[{pair[0]},{pair[1]}]"

    def js_opt_num(v) -> str:
        """Format an optional number as JS value (null if None)."""
        return "null" if v is None else str(v)

    if exhibit:
        return (
            f"  {{id:'{app_id}',name:{js_str(name)},latin:'{latin}',"
            f"pack:'{pack}',continents:{conts_js},biomes:{biomes_js},"
            f"img:'{img}',enrichedBy:[],guestWalk:false,exhibit:true,"
            f"terrain:{{grassS:[0,100],grassL:[0,100],soil:[0,100],rock:[0,100],sand:[0,100],snow:[0,100]}},"
            f"plants:[0,100]}},"
        )

    t          = animal.get("terrain", {})
    plants     = animal.get("plants", [0, 100])
    land          = animal.get("landMin", 0)
    land_group    = animal.get("landMinGroup")
    spa           = animal.get("spacePerAdditional")
    aquatic_min   = animal.get("aquaticMin")
    aquatic_per   = animal.get("aquaticPerAdditional")
    aquatic_depth = animal.get("aquaticDepth")
    climb_min     = animal.get("climbMin")
    deep_swim_min = animal.get("deepSwimMin")
    shelter_min   = animal.get("shelterMin")
    temp_min      = animal.get("tempMin")
    temp_max      = animal.get("tempMax")
    adults_min    = animal.get("adultsMin")
    adults_max    = animal.get("adultsMax")
    min_litter    = animal.get("minLitterSize")
    max_litter    = animal.get("maxLitterSize")
    gestation     = animal.get("gestationTime")
    inter_birth   = animal.get("interBirthTime")
    max_m_single  = animal.get("maxMalesSingle")
    max_f_single  = animal.get("maxFemalesSingle")
    max_m_both    = animal.get("maxMalesBoth")
    max_f_both    = animal.get("maxFemalesBoth")
    is_pred       = animal.get("isPredator", False)
    well_defended = animal.get("wellDefended", False)
    trophic       = animal.get("adultTrophicLevel", "")
    temperament   = animal.get("temperament", "")
    climber       = animal.get("climber",   False)
    can_swim      = animal.get("canSwim",   False)
    deep_diver    = animal.get("deepDiver", False)
    burrower      = animal.get("burrower",  False)

    terrain_js = (
        f"{{grassS:{rng(t.get('grassS', [0,100]))},"
        f"grassL:{rng(t.get('grassL', [0,100]))},"
        f"soil:{rng(t.get('soil',   [0,100]))},"
        f"rock:{rng(t.get('rock',   [0,100]))},"
        f"sand:{rng(t.get('sand',   [0,100]))},"
        f"snow:{rng(t.get('snow',   [0,100]))}}}"
    )
    if bar.get("grade") is not None and bar.get("height") is not None:
        barrier_js = f"{{grade:{bar['grade']},height:{bar['height']}}}"
    else:
        barrier_js = "null"

    def tf(b: bool) -> str:
        return "true" if b else "false"

    return (
        f"  {{id:'{app_id}',name:{js_str(name)},latin:'{latin}',"
        f"pack:'{pack}',continents:{conts_js},biomes:{biomes_js},"
        f"img:'{img}',enrichedBy:{enriched_js},guestWalk:{tf(guest)},"
        f"exhibit:false,terrain:{terrain_js},"
        f"plants:{rng(plants)},"
        f"landMin:{land},landMinGroup:{js_opt_num(land_group)},spacePerAdditional:{js_opt_num(spa)},"
        f"aquaticMin:{js_opt_num(aquatic_min)},aquaticPerAdditional:{js_opt_num(aquatic_per)},"
        f"aquaticDepth:{js_opt_num(aquatic_depth)},"
        f"climbMin:{js_opt_num(climb_min)},deepSwimMin:{js_opt_num(deep_swim_min)},"
        f"shelterMin:{js_opt_num(shelter_min)},"
        f"tempMin:{js_opt_num(temp_min)},tempMax:{js_opt_num(temp_max)},"
        f"adultsMin:{js_opt_num(adults_min)},adultsMax:{js_opt_num(adults_max)},"
        f"minLitterSize:{js_opt_num(min_litter)},maxLitterSize:{js_opt_num(max_litter)},"
        f"gestationTime:{js_opt_num(gestation)},interBirthTime:{js_opt_num(inter_birth)},"
        f"maxMalesSingle:{js_opt_num(max_m_single)},maxFemalesSingle:{js_opt_num(max_f_single)},"
        f"maxMalesBoth:{js_opt_num(max_m_both)},maxFemalesBoth:{js_opt_num(max_f_both)},"
        f"isPredator:{tf(is_pred)},wellDefended:{tf(well_defended)},"
        f"trophicLevel:'{trophic}',temperament:'{temperament}',"
        f"climber:{tf(climber)},canSwim:{tf(can_swim)},deepDiver:{tf(deep_diver)},burrower:{tf(burrower)},"
        f"barrier:{barrier_js}}},"
    )


# ---------------------------------------------------------------------------
# Main extraction logic
# ---------------------------------------------------------------------------

def extract_all(cobra_tools: Path, game_dir: Path, extract_root: Path) -> tuple[dict, dict]:
    """
    Extract FDB and localisation files from all content packs.

    Returns (animals, loc_map) where:
      animals  — dict keyed by game_id
      loc_map  — dict keyed by game_id_lower with {name, latin, barrier}
    """
    content_dirs = find_content_dirs(game_dir)
    print(f"Found {len(content_dirs)} content directories.")

    terrain_map:         dict[str, dict]  = {}
    habitat_map:         dict[str, dict]  = {}  # plants + optional temp
    space_map:           dict[str, dict]  = {}  # land/aquatic/climb/shelter space
    barrier_map:         dict[str, dict]  = {}
    guest_walk_set:      set[str]         = set()
    enrichment_map:      dict[str, set]   = {}
    definitions:         dict[str, str]   = {}
    exhibit_set:         set[str]         = set()
    biome_pref_map:      dict[str, list]  = {}
    continent_pref_map:  dict[str, list]  = {}
    population_map:      dict[str, dict]  = {}  # adultsMin/adultsMax
    fertility_map:       dict[str, dict]  = {}  # minLitterSize/maxLitterSize/gestationTime/interBirthTime
    gender_ratio_map:    dict[str, dict]  = {}  # maxMales/FemalesSingle/Both
    interspecies_map:    dict[str, dict]  = {}  # per-animal predation profile
    behavior_map:        dict[str, dict]  = {}  # climber/canSwim/deepDiver/burrower
    loc_map:             dict[str, dict]  = {}  # game_id_lower → {name, latin, barrier}

    for content_dir in content_dirs:
        ovl_path = content_dir / "Main.ovl"
        if not ovl_path.exists():
            continue

        pack_name = content_dir.name
        out_dir   = extract_root / pack_name
        print(f"  Extracting {pack_name}/Main.ovl …", end=" ", flush=True)

        fdb_files = extract_fdb_files(cobra_tools, ovl_path, out_dir)
        print(f"{len(fdb_files)} FDB files.", end="  ", flush=True)

        for fdb in fdb_files:
            fname = fdb.name.lower()
            conn  = open_db(fdb)
            if conn is None:
                continue
            try:
                if fname.endswith("animals.fdb"):
                    terrain_map.update(query_terrain(conn))
                    habitat_map.update(query_habitat(conn))
                    space_map.update(query_space(conn))
                    guest_walk_set.update(query_guest_walk(conn))
                    for animal, partners in query_enrichment(conn).items():
                        enrichment_map.setdefault(animal, set()).update(partners)
                    definitions.update(query_definitions(conn))
                    biome_pref_map.update(query_biome_prefs(conn))
                    continent_pref_map.update(query_continent_prefs(conn))
                    for animal, data in query_population(conn).items():
                        population_map.setdefault(animal, {}).update(data)
                    for animal, data in query_fertility(conn).items():
                        fertility_map[animal] = data
                    for animal, data in query_gender_ratios(conn).items():
                        gender_ratio_map[animal] = data
                    for animal, profile in query_predation_profile(conn).items():
                        interspecies_map[animal] = profile
                    for animal, data in query_behaviors(conn).items():
                        entry = behavior_map.setdefault(animal, {
                            "climber": False, "canSwim": False,
                            "deepDiver": False, "burrower": False,
                        })
                        for k in ("climber", "canSwim", "deepDiver", "burrower"):
                            entry[k] = entry[k] or data.get(k, False)
                    # isPredator is derived from InterspeciesInteractionData.PredatorPrey
                elif fname.endswith("zoopedia.fdb"):
                    barrier_map.update(query_barrier(conn))
                elif fname.endswith("exhibits.fdb"):
                    exhibit_set.update(query_exhibits(conn))
                    definitions.update(query_definitions(conn))
            finally:
                conn.close()

        # Extract localisation OVL for display names, latin names, and barrier text.
        loc_ovl = find_loc_ovl(content_dir)
        if loc_ovl:
            loc_dir = out_dir / "loc"
            print(f"Loc …", end=" ", flush=True)
            extract_loc_files(cobra_tools, loc_ovl, loc_dir)
            for gid_lower, data in parse_loc_data(loc_dir).items():
                loc_map.setdefault(gid_lower, {}).update(data)
        print()

    # Merge into unified animal records
    all_ids = set(terrain_map) | exhibit_set
    animals = {}

    for game_id in sorted(all_ids):
        raw_pack   = definitions.get(game_id, "")
        pack_name  = CONTENT_PACK_NAMES.get(raw_pack, raw_pack or "Unknown")
        is_exhibit = game_id in exhibit_set and game_id not in terrain_map

        record: dict = {
            "game_id":              game_id,
            "pack":                 pack_name,
            "content_pack_raw":     raw_pack,
            "exhibit":              is_exhibit,
            "guestWalk":            game_id in guest_walk_set,
            "enrichedBy":           sorted(enrichment_map.get(game_id, set())),
            "biomes_from_game":     sorted(biome_pref_map.get(game_id, [])),
            "continents_from_game": sorted(continent_pref_map.get(game_id, [])),
        }

        if not is_exhibit:
            space_data    = space_map.get(game_id, {})
            habitat_data  = habitat_map.get(game_id, {})
            pop_data      = population_map.get(game_id, {})
            fertility_data = fertility_map.get(game_id, {})
            gender_data   = gender_ratio_map.get(game_id, {})
            beh_data      = behavior_map.get(game_id, {})
            pred_data     = interspecies_map.get(game_id, {})

            adults_min       = pop_data.get("adultsMin")
            adults_max       = pop_data.get("adultsMax")
            land_min         = space_data.get("landMin", 0)
            spa              = space_data.get("spacePerAdditional")
            max_females_both = gender_data.get("maxFemalesBoth")
            max_litter       = fertility_data.get("maxLitterSize")

            # Compute family-group maximum space (largest group including juveniles):
            # Total animals = MaxPopulation adults + (MaxFemalesBoth × MaxLitterSize) juveniles
            # landMinGroup = MinimumSpace + SpacePerAdditionalAnimal × (total − 1)
            # Validated against Villanelle's spreadsheet: Aardvark → 330 + 60×(2+1×1−1) = 450 ✓
            if spa is not None and adults_max is not None:
                juveniles      = (max_females_both or 0) * (max_litter or 0)
                total_max      = adults_max + juveniles
                land_min_group: int | None = land_min + spa * max(0, total_max - 1)
            else:
                land_min_group = None

            record["terrain"]              = terrain_map.get(game_id, {})
            record["plants"]               = habitat_data.get("plants", [0, 100])
            record["landMin"]              = land_min
            record["spacePerAdditional"]   = spa
            record["landMinGroup"]         = land_min_group
            # Aquatic/climbing/shelter space (from SpaceRequirements)
            record["aquaticMin"]           = space_data.get("aquaticMin")
            record["aquaticPerAdditional"] = space_data.get("aquaticPerAdditional")
            record["aquaticDepth"]         = space_data.get("aquaticDepth")
            record["climbMin"]             = space_data.get("climbMin")
            record["climbPerAdditional"]   = space_data.get("climbPerAdditional")
            record["deepSwimMin"]          = space_data.get("deepSwimMin")
            record["deepSwimPerAdditional"]= space_data.get("deepSwimPerAdditional")
            record["shelterMin"]           = space_data.get("shelterMin")
            record["juvenileSwims"]        = space_data.get("juvenileSwims", False)
            record["juvenileDeepSwims"]    = space_data.get("juvenileDeepSwims", False)
            record["tempMin"]              = habitat_data.get("tempMin")
            record["tempMax"]              = habitat_data.get("tempMax")
            record["adultsMin"]            = adults_min
            record["adultsMax"]            = adults_max
            # Fertility (from FertilityData)
            record["minLitterSize"]        = fertility_data.get("minLitterSize")
            record["maxLitterSize"]        = max_litter
            record["gestationTime"]        = fertility_data.get("gestationTime")
            record["interBirthTime"]       = fertility_data.get("interBirthTime")
            # Group composition (from DesiredGenderRatios)
            record["maxMalesSingle"]       = gender_data.get("maxMalesSingle")
            record["maxFemalesSingle"]     = gender_data.get("maxFemalesSingle")
            record["maxMalesBoth"]         = gender_data.get("maxMalesBoth")
            record["maxFemalesBoth"]       = max_females_both
            # Predation profile (from InterspeciesInteractionData)
            record["predatorPrey"]         = pred_data.get("predatorPrey", "")
            record["isPredator"]           = pred_data.get("predatorPrey") == "Predator"
            record["adultTrophicLevel"]    = pred_data.get("adultTrophicLevel", "")
            record["juvenileTrophicLevel"] = pred_data.get("juvenileTrophicLevel", "")
            record["temperament"]          = pred_data.get("temperament", "")
            # wellDefended: LevelApex prey cannot be killed by any predator (e.g. tortoises)
            record["wellDefended"]         = pred_data.get("adultTrophicLevel") == "LevelApex"
            record["hasDefensiveIntimidate"] = pred_data.get("hasDefensiveIntimidate", False)
            record["defensiveIntimidationRadius"] = pred_data.get("defensiveIntimidationRadius")
            # Behaviour flags (from IdleBehaviourWeights)
            record["climber"]              = beh_data.get("climber",   False)
            record["canSwim"]              = beh_data.get("canSwim",   False)
            record["deepDiver"]            = beh_data.get("deepDiver", False)
            record["burrower"]             = beh_data.get("burrower",  False)
            record["barrier"]              = barrier_map.get(game_id, {})

        animals[game_id] = record

    return animals, loc_map


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract Planet Zoo animal data from game OVL files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cobra-tools", required=True, metavar="PATH",
        help="Directory containing ovl_tool_cmd.py",
    )
    parser.add_argument(
        "--game-dir", required=True, metavar="PATH",
        help="Planet Zoo game directory (contains win64/ovldata/)",
    )
    parser.add_argument(
        "--output", default="extracted_animals.json", metavar="PATH",
        help="Output JSON file (default: extracted_animals.json)",
    )
    parser.add_argument(
        "--js-output", default="animals.js", metavar="PATH",
        help="Output JS file (default: animals.js — the live data file)",
    )
    parser.add_argument(
        "--extract-dir", default=None, metavar="PATH",
        help="Directory for extracted OVL files (default: system temp dir)",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="Keep extracted OVL files after the script finishes",
    )
    args = parser.parse_args()

    cobra_tools = Path(args.cobra_tools).resolve()
    game_dir    = Path(args.game_dir).resolve()

    if not (cobra_tools / "ovl_tool_cmd.py").exists():
        sys.exit(f"ERROR: ovl_tool_cmd.py not found in {cobra_tools}")
    if not game_dir.exists():
        sys.exit(f"ERROR: Game directory not found: {game_dir}")

    tmp_owned = False
    if args.extract_dir:
        extract_root = Path(args.extract_dir).resolve()
        extract_root.mkdir(parents=True, exist_ok=True)
    else:
        extract_root = Path(tempfile.mkdtemp(prefix="pz_extract_"))
        tmp_owned = True

    print(f"Extracting OVL files to: {extract_root}")
    print()

    try:
        animals, loc_map = extract_all(cobra_tools, game_dir, extract_root)
    finally:
        if not args.no_cleanup:
            shutil.rmtree(extract_root, ignore_errors=True)
            print(f"\nCleaned up {extract_root}")
        else:
            print(f"\nExtracted files kept at: {extract_root}")

    # Serialise sets to lists for JSON
    json_animals = {
        gid: {**rec, "enrichedBy": list(rec.get("enrichedBy", []))}
        for gid, rec in animals.items()
    }

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(json_animals, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(animals)} animals to {output_path}")

    js_path = Path(args.js_output)
    if js_path.exists():
        backup_path = js_path.with_suffix(".js.bak")
        shutil.copy2(js_path, backup_path)
        print(f"Backed up {js_path} -> {backup_path}")

    habitat_count = sum(1 for a in animals.values() if not a["exhibit"])
    exhibit_count = sum(1 for a in animals.values() if     a["exhibit"])
    lines = [
        "// Generated by extract_pz_data.py — do not edit by hand.",
        f"// {habitat_count} habitat animals, {exhibit_count} exhibit animals",
        "// All data extracted from game files. img filename = animal id.",
        "",
        "const ANIMALS = [",
        "// ===== HABITAT ANIMALS =====",
    ]
    for rec in sorted(animals.values(), key=lambda r: r["game_id"]):
        if not rec["exhibit"]:
            lines.append(format_js_entry(rec, loc_map))
    lines += ["", "// ===== EXHIBIT ANIMALS ====="]
    for rec in sorted(animals.values(), key=lambda r: r["game_id"]):
        if rec["exhibit"]:
            lines.append(format_js_entry(rec, loc_map))
    lines.append("];")

    js_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote JS entries to {js_path}")

    # Report animals with no barrier data after both FDB and loc sources
    missing_barrier = [
        gid for gid, rec in animals.items()
        if not rec["exhibit"]
        and not rec.get("barrier")
        and not loc_map.get(gid.lower(), {}).get("barrier")
    ]
    if missing_barrier:
        print(f"\nAnimals with no barrier data ({len(missing_barrier)}):")
        for gid in missing_barrier:
            print(f"  {gid}")

    # Report animals with no latin name
    missing_latin = [
        gid for gid in animals
        if not loc_map.get(gid.lower(), {}).get("latin")
    ]
    if missing_latin:
        print(f"\nAnimals with no latin name ({len(missing_latin)}):")
        for gid in missing_latin:
            print(f"  {gid}")


if __name__ == "__main__":
    main()

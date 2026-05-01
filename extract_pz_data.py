#!/usr/bin/env python3
"""
Extract Planet Zoo animal habitat data from game OVL files using cobra-tools.

For each habitat animal found, outputs:
  terrain slider ranges (grassS, grassL, soil, rock, sand, snow)
  plant coverage range
  minimum enclosure land area
  barrier grade and height
  enrichedBy partner names
  guestWalk flag

For exhibit animals, outputs the exhibit flag with no terrain/barrier data.

Usage:
  python extract_pz_data.py \\
      --cobra-tools "C:/path/to/cobra-tools-master" \\
      --game-dir "C:/Program Files (x86)/Steam/steamapps/common/Planet Zoo" \\
      [--output extracted_animals.json] \\
      [--js-output extracted_animals.js] \\
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


def extract_fdb_files(cobra_tools: Path, ovl_path: Path, out_dir: Path) -> list[Path]:
    """
    Extract all .fdb files from a single OVL using cobra-tools.
    Returns list of extracted .fdb paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(cobra_tools / "ovl_tool_cmd.py"),
        "extract",
        "--game", "Planet Zoo",
        "--type", "fdb",
        "--output", str(out_dir),
        str(ovl_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cobra_tools),
    )
    if "SUCCESS | Extracted" not in result.stdout and "SUCCESS | Extracting" not in result.stdout:
        # May still have succeeded with warnings
        if "SUCCESS" not in result.stdout:
            print(f"  WARNING: cobra-tools output for {ovl_path.name}:")
            for line in result.stdout.splitlines()[-5:]:
                print(f"    {line}")

    return list(out_dir.glob("*.fdb"))


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
    """AnimalHabitatRequirements → plant coverage (0–100 %)."""
    if not table_exists(conn, "AnimalHabitatRequirements"):
        return {}
    out = {}
    for row in conn.execute(
        "SELECT AnimalType, MinPlantCoverage, MaxPlantCoverage FROM AnimalHabitatRequirements"
    ):
        animal = row["AnimalType"]
        out[animal] = {
            "plants": [
                round((row["MinPlantCoverage"] or 0) * 100),
                round((row["MaxPlantCoverage"] or 0) * 100),
            ]
        }
    return out


def query_space(conn: sqlite3.Connection) -> dict:
    """SpaceRequirements → minimum land area in m²."""
    if not table_exists(conn, "SpaceRequirements"):
        return {}
    out = {}
    for row in conn.execute(
        "SELECT AnimalType, MinimumSpace FROM SpaceRequirements"
    ):
        if row["MinimumSpace"] is not None:
            out[row["AnimalType"]] = int(round(row["MinimumSpace"]))
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


def query_exhibits(conn: sqlite3.Connection) -> set:
    """Return set of animal types that are exhibits (from *exhibits.fdb)."""
    # Exhibit databases have different schemas depending on the exhibit type.
    # We just want the species/animal type names. Common table names:
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
# Name lookup helpers
# ---------------------------------------------------------------------------

def build_id_to_name_map(index_html: Path) -> dict[str, str]:
    """
    Parse the ANIMALS array in index.html to build game_id → display_name.
    Uses camelCase ↔ app id mapping.
    """
    if not index_html.exists():
        return {}
    text = index_html.read_text(encoding="utf-8")
    # Extract id and name pairs
    entries = re.findall(r"\{id:'([^']+)',name:(['\"][^'\"]+['\"])", text)
    result = {}
    for app_id, raw_name in entries:
        name = raw_name.strip("'\"")
        # Build likely camelCase game ID from app id (snake_case)
        game_id = "".join(w.capitalize() for w in app_id.split("_"))
        result[game_id] = name
        result[app_id] = name  # also map app_id directly
    return result


def game_id_to_display(game_id: str, name_map: dict) -> str:
    """Return display name for a game ID, falling back to auto-generated."""
    if game_id in name_map:
        return name_map[game_id]
    return camel_to_display(game_id)


def display_to_app_id(display_name: str) -> str:
    """Convert display name to snake_case app id: 'Snow Leopard' → 'snow_leopard'."""
    clean = re.sub(r"[^a-zA-Z0-9 ]", "", display_name)
    return "_".join(clean.lower().split())


# ---------------------------------------------------------------------------
# JS formatting
# ---------------------------------------------------------------------------

def format_js_entry(animal: dict, name_map: dict) -> str:
    """Format one animal dict as a single-line JS object matching the app format."""
    game_id  = animal["game_id"]
    name     = game_id_to_display(game_id, name_map)
    app_id   = display_to_app_id(name)
    latin    = animal.get("latin", "")
    pack     = animal.get("pack", "Unknown")
    conts    = animal.get("continents", [])
    biomes   = animal.get("biomes", [])
    img      = animal.get("img", "")
    exhibit  = animal.get("exhibit", False)
    guest    = animal.get("guestWalk", False)

    # enrichedBy: convert game IDs → display names
    raw_enriched = sorted(animal.get("enrichedBy", []))
    enriched_names = [game_id_to_display(e, name_map) for e in raw_enriched]
    def js_str(s):
        if "'" in s:
            return f'"{s}"'
        return f"'{s}'"
    enriched_js = "[" + ",".join(js_str(n) for n in enriched_names) + "]"

    conts_js  = "[" + ",".join(f"'{c}'" for c in conts) + "]"
    biomes_js = "[" + ",".join(f"'{b}'" for b in biomes) + "]"

    if exhibit:
        return (
            f"  {{id:'{app_id}',name:{js_str(name)},latin:'{latin}',"
            f"pack:'{pack}',continents:{conts_js},biomes:{biomes_js},"
            f"img:'{img}',enrichedBy:[],guestWalk:false,exhibit:true,"
            f"terrain:{{grassS:[0,100],grassL:[0,100],soil:[0,100],rock:[0,100],sand:[0,100],snow:[0,100]}},"
            f"plants:[0,100]}},"
        )

    t = animal.get("terrain", {})
    plants = animal.get("plants", [0, 100])
    land   = animal.get("landMin", 0)
    bar    = animal.get("barrier", {})

    def rng(pair):
        return f"[{pair[0]},{pair[1]}]"

    terrain_js = (
        f"{{grassS:{rng(t.get('grassS',[0,100]))},"
        f"grassL:{rng(t.get('grassL',[0,100]))},"
        f"soil:{rng(t.get('soil',[0,100]))},"
        f"rock:{rng(t.get('rock',[0,100]))},"
        f"sand:{rng(t.get('sand',[0,100]))},"
        f"snow:{rng(t.get('snow',[0,100])}}}}"
    )
    barrier_js = f"{{grade:{bar.get('grade','?')},height:{bar.get('height','?')}}}"

    return (
        f"  {{id:'{app_id}',name:{js_str(name)},latin:'{latin}',"
        f"pack:'{pack}',continents:{conts_js},biomes:{biomes_js},"
        f"img:'{img}',enrichedBy:{enriched_js},guestWalk:{'true' if guest else 'false'},"
        f"exhibit:false,terrain:{terrain_js},"
        f"plants:{rng(plants)},landMin:{land},barrier:{barrier_js}}},"
    )


# ---------------------------------------------------------------------------
# Main extraction logic
# ---------------------------------------------------------------------------

def extract_all(cobra_tools: Path, game_dir: Path, extract_root: Path) -> dict:
    """
    Extract FDB files from all content packs and return merged animal data.

    Returns dict keyed by game_id with fields:
      terrain, plants, landMin, barrier, enrichedBy, guestWalk,
      exhibit, pack, content_pack_raw
    """
    content_dirs = find_content_dirs(game_dir)
    print(f"Found {len(content_dirs)} content directories.")

    # Accumulated data across all content packs
    terrain_map:    dict[str, dict]  = {}
    habitat_map:    dict[str, dict]  = {}
    space_map:      dict[str, int]   = {}
    barrier_map:    dict[str, dict]  = {}
    guest_walk_set: set[str]         = set()
    enrichment_map: dict[str, set]   = {}
    definitions:    dict[str, str]   = {}  # game_id → raw ContentPack value
    exhibit_set:    set[str]         = set()

    for content_dir in content_dirs:
        ovl_path = content_dir / "Main.ovl"
        if not ovl_path.exists():
            continue

        pack_name = content_dir.name  # e.g. "Content16"
        out_dir = extract_root / pack_name
        print(f"  Extracting {pack_name}/Main.ovl …", end=" ", flush=True)

        fdb_files = extract_fdb_files(cobra_tools, ovl_path, out_dir)
        print(f"{len(fdb_files)} FDB files extracted.")

        for fdb in fdb_files:
            fname = fdb.name.lower()
            conn = open_db(fdb)
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

                elif fname.endswith("zoopedia.fdb"):
                    barrier_map.update(query_barrier(conn))

                elif fname.endswith("exhibits.fdb"):
                    exhibit_set.update(query_exhibits(conn))

            finally:
                conn.close()

    # Merge into unified animal records
    all_ids = set(terrain_map) | exhibit_set
    animals = {}

    for game_id in sorted(all_ids):
        raw_pack  = definitions.get(game_id, "")
        pack_name = CONTENT_PACK_NAMES.get(raw_pack, raw_pack or "Unknown")
        is_exhibit = game_id in exhibit_set and game_id not in terrain_map

        record: dict = {
            "game_id":          game_id,
            "pack":             pack_name,
            "content_pack_raw": raw_pack,
            "exhibit":          is_exhibit,
            "guestWalk":        game_id in guest_walk_set,
            "enrichedBy":       sorted(enrichment_map.get(game_id, set())),
        }

        if not is_exhibit:
            record["terrain"] = terrain_map.get(game_id, {})
            record["plants"]  = habitat_map.get(game_id, {}).get("plants", [0, 100])
            record["landMin"] = space_map.get(game_id, 0)
            record["barrier"] = barrier_map.get(game_id, {})

        animals[game_id] = record

    return animals


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
        "--js-output", default="extracted_animals.js", metavar="PATH",
        help="Output JS entries file (default: extracted_animals.js)",
    )
    parser.add_argument(
        "--extract-dir", default=None, metavar="PATH",
        help="Directory for extracted OVL files (default: system temp dir)",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="Keep extracted OVL files after the script finishes",
    )
    parser.add_argument(
        "--index-html", default=None, metavar="PATH",
        help="Path to index.html for existing animal name lookup (optional)",
    )
    args = parser.parse_args()

    cobra_tools = Path(args.cobra_tools).resolve()
    game_dir    = Path(args.game_dir).resolve()

    if not (cobra_tools / "ovl_tool_cmd.py").exists():
        sys.exit(f"ERROR: ovl_tool_cmd.py not found in {cobra_tools}")
    if not game_dir.exists():
        sys.exit(f"ERROR: Game directory not found: {game_dir}")

    # Resolve index.html for name lookups
    index_html = Path(args.index_html) if args.index_html else Path(__file__).parent / "index.html"
    name_map = build_id_to_name_map(index_html)
    print(f"Loaded {len(name_map)} existing animal names from {index_html.name}.")

    # Set up extract directory
    tmp_owned = False
    if args.extract_dir:
        extract_root = Path(args.extract_dir)
        extract_root.mkdir(parents=True, exist_ok=True)
    else:
        extract_root = Path(tempfile.mkdtemp(prefix="pz_extract_"))
        tmp_owned = True

    print(f"Extracting OVL files to: {extract_root}")
    print()

    try:
        animals = extract_all(cobra_tools, game_dir, extract_root)
    finally:
        if not args.no_cleanup and tmp_owned:
            shutil.rmtree(extract_root, ignore_errors=True)
            print(f"\nCleaned up {extract_root}")
        elif not args.no_cleanup and not tmp_owned:
            shutil.rmtree(extract_root, ignore_errors=True)
            print(f"\nCleaned up {extract_root}")
        else:
            print(f"\nExtracted files kept at: {extract_root}")

    # Serialise sets to lists for JSON
    json_animals = {
        gid: {**rec, "enrichedBy": list(rec.get("enrichedBy", []))}
        for gid, rec in animals.items()
    }

    # Write JSON
    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(json_animals, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(animals)} animals to {output_path}")

    # Write JS entries
    js_path = Path(args.js_output)
    habitat_count = sum(1 for a in animals.values() if not a["exhibit"])
    exhibit_count = sum(1 for a in animals.values() if a["exhibit"])
    lines = [
        f"// Generated by extract_pz_data.py",
        f"// {habitat_count} habitat animals, {exhibit_count} exhibit animals",
        f"// Missing barrier data is shown as grade:? height:? — fill from in-game Zoopedia.",
        f"// Missing latin names and biome/continent lists must be filled manually.",
        "",
        "// ===== HABITAT ANIMALS =====",
    ]
    for game_id, rec in sorted(animals.items()):
        if not rec["exhibit"]:
            lines.append(format_js_entry(rec, name_map))
    lines += ["", "// ===== EXHIBIT ANIMALS ====="]
    for game_id, rec in sorted(animals.items()):
        if rec["exhibit"]:
            lines.append(format_js_entry(rec, name_map))

    js_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote JS entries to {js_path}")

    # Summary
    missing_barrier = [
        gid for gid, rec in animals.items()
        if not rec["exhibit"] and not rec.get("barrier")
    ]
    if missing_barrier:
        print(f"\nAnimals with no barrier data ({len(missing_barrier)}) — check zoopedia DBs or wiki:")
        for gid in missing_barrier:
            print(f"  {gid}")


if __name__ == "__main__":
    main()

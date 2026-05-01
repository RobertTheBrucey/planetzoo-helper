#!/usr/bin/env bash
# Cloudflare Pages build script.
# Runs in a temporary clone of the repo — changes here do not affect the source.
set -euo pipefail

# Bake the current UTC timestamp into the staging banner placeholder.
BUILD_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
sed -i "s|@@BUILD_TIME@@|${BUILD_TS}|g" index.html
echo "Build timestamp: ${BUILD_TS}"

# Remove files that are only used locally and don't need to be served.
rm -f extract_pz_data.py download_images.py missing_terrain_data.txt Feature_Requests

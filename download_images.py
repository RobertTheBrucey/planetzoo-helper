#!/usr/bin/env python3
"""Download missing animal portrait images from the Planet Zoo wiki."""

import os
import sys
import time
import urllib.request
import urllib.parse
import json
import re

IMG_DIR = os.path.join(os.path.dirname(__file__), 'img')

# app_id → wiki article title (override when display name differs from wiki title)
WIKI_TITLE_OVERRIDES = {
    'bornean_elephant':  'Bornean Elephant',
    'african_leopard':   'African Leopard',
    'pallass_cat':       "Pallas's Cat",
    'coquerels_sifaka':  "Coquerel's Sifaka",
    'kirks_dik_dik':     "Kirk's Dik-Dik",
    'pre_davids_deer':   "Père David's Deer",
    'spectacled_bear':   'Spectacled Bear',
}

MISSING = [
    # Barnyard DLC
    ('alpaca',                  'Alpaca'),
    ('alpine_goat',             'Alpine Goat'),
    ('american_standard_donkey','American Standard Donkey'),
    ('highland_cattle',         'Highland Cattle'),
    ('hill_radnor_sheep',       'Hill Radnor Sheep'),
    ('sussex_chicken',          'Sussex Chicken'),
    ('tamworth_pig',            'Tamworth Pig'),
    # Other missing portraits
    ('european_peacock',        'European Peacock'),
    ('blackbuck',               'Blackbuck'),
    ('wisent',                  'Wisent'),
    ('nilgai',                  'Nilgai'),
    ('brown_throated_sloth',    'Brown-Throated Sloth'),
    ('takin',                   'Takin'),
    ('coyote',                  'Coyote'),
    ('markhor',                 'Markhor'),
    ('african_spurred_tortoise','African Spurred Tortoise'),
    ('mute_swan',               'Mute Swan'),
    ('collared_peccary',        'Collared Peccary'),
    ('pre_davids_deer',         "Père David's Deer"),
    ('bornean_elephant',        'Bornean Elephant'),
    ('wolverine',               'Wolverine'),
    ('ocelot',                  'Ocelot'),
    ('lion_tailed_macaque',     'Lion-Tailed Macaque'),
    ('kirks_dik_dik',           "Kirk's Dik-Dik"),
    ('honey_badger',            'Honey Badger'),
    ('sloth_bear',              'Sloth Bear'),
    ('japanese_raccoon_dog',    'Japanese Raccoon Dog'),
    ('pallass_cat',             "Pallas's Cat"),
    ('bighorn_sheep',           'Bighorn Sheep'),
    ('african_leopard',         'African Leopard'),
    ('hamadryas_baboon',        'Hamadryas Baboon'),
    ('american_flamingo',       'American Flamingo'),
    ('white_faced_saki',        'White-Faced Saki'),
    ('coquerels_sifaka',        "Coquerel's Sifaka"),
    ('greater_rhea',            'Greater Rhea'),
    ('saiga',                   'Saiga'),
    ('bush_dog',                'Bush Dog'),
    ('wild_boar',               'Wild Boar'),
    ('hermanns_tortoise',       "Hermann's Tortoise"),
    ('spectacled_bear',         'Spectacled Bear'),
]

API_BASE = 'https://planetzoo.fandom.com/api.php'


def wiki_api(params):
    params['format'] = 'json'
    url = API_BASE + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'PlanetZooImageFetcher/1.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def get_image_url_from_page(title):
    """Return the URL of the first image in the animal's infobox (or any image)."""
    data = wiki_api({
        'action': 'query',
        'titles': title,
        'prop': 'images',
        'imlimit': '20',
    })
    pages = data.get('query', {}).get('pages', {})
    page = next(iter(pages.values()))
    images = page.get('images', [])

    # Prefer the infobox portrait — typically named like "AnimalName PZ Artwork.png"
    # or just "AnimalName.png"
    for img in images:
        name = img['title']
        low = name.lower()
        if 'artwork' in low or 'portrait' in low or 'icon' in low:
            return resolve_image_url(name)

    # Fall back to first non-svg image
    for img in images:
        name = img['title']
        if not name.lower().endswith('.svg'):
            url = resolve_image_url(name)
            if url:
                return url
    return None


def resolve_image_url(file_title):
    """Return direct URL for a wiki File: title."""
    data = wiki_api({
        'action': 'query',
        'titles': file_title,
        'prop': 'imageinfo',
        'iiprop': 'url',
    })
    pages = data.get('query', {}).get('pages', {})
    page = next(iter(pages.values()))
    info = page.get('imageinfo', [])
    if info:
        return info[0]['url']
    return None


def download(url, dest_path):
    req = urllib.request.Request(url, headers={'User-Agent': 'PlanetZooImageFetcher/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    with open(dest_path, 'wb') as f:
        f.write(data)


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    failed = []

    for app_id, display_name in MISSING:
        dest = os.path.join(IMG_DIR, f'{app_id}.png')
        if os.path.exists(dest):
            print(f'  skip  {display_name}')
            continue

        wiki_title = WIKI_TITLE_OVERRIDES.get(app_id, display_name)
        print(f'  fetch {display_name} ("{wiki_title}") ... ', end='', flush=True)

        try:
            img_url = get_image_url_from_page(wiki_title)
            if not img_url:
                print('no image found')
                failed.append((app_id, display_name, 'no image on page'))
                continue

            download(img_url, dest)
            print(f'ok ({os.path.getsize(dest):,} bytes)')
        except Exception as e:
            print(f'ERROR: {e}')
            failed.append((app_id, display_name, str(e)))

        time.sleep(0.5)  # be polite to the wiki

    print()
    if failed:
        print(f'{len(failed)} failed:')
        for app_id, name, reason in failed:
            print(f'  {name}: {reason}')
    else:
        print('All images downloaded successfully.')


if __name__ == '__main__':
    main()

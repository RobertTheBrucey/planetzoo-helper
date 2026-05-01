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

# Latin name → wiki article title (override when they differ)
WIKI_TITLE_OVERRIDES = {
    'elephas_maximus_borneensis': 'Bornean Elephant',
    'panthera_pardus_pardus':     'African Leopard',
    'otocolobus_manul':           "Pallas's Cat",
    'propithecus_coquereli':      "Coquerel's Sifaka",
    'madoqua_kirkii':             "Kirk's Dik-Dik",
    'elaphurus_davidianus':       "Père David's Deer",
    'tremarctos_ornatus':         'Spectacled Bear',
}

MISSING = [
    ('aglais_io',                 'European Peacock'),
    ('antilope_cervicapra',       'Blackbuck'),
    ('bison_bonasus',             'Wisent'),
    ('boselaphus_tragocamelus',   'Nilgai'),
    ('bradypus_variegatus',       'Brown-Throated Sloth'),
    ('budorcas_taxicolor',        'Takin'),
    ('canis_latrans',             'Coyote'),
    ('capra_falconeri',           'Markhor'),
    ('centrochelys_sulcata',      'African Spurred Tortoise'),
    ('cygnus_olor',               'Mute Swan'),
    ('dicotyles_tajacu',          'Collared Peccary'),
    ('elaphurus_davidianus',      "Père David's Deer"),
    ('elephas_maximus_borneensis','Bornean Elephant'),
    ('gulo_gulo',                 'Wolverine'),
    ('leopardus_pardalis',        'Ocelot'),
    ('macaca_silenus',            'Lion-Tailed Macaque'),
    ('madoqua_kirkii',            "Kirk's Dik-Dik"),
    ('mellivora_capensis',        'Honey Badger'),
    ('melursus_ursinus',          'Sloth Bear'),
    ('nyctereutes_viverrinus',    'Japanese Raccoon Dog'),
    ('otocolobus_manul',          "Pallas's Cat"),
    ('ovis_canadensis',           'Bighorn Sheep'),
    ('panthera_pardus_pardus',    'African Leopard'),
    ('papio_hamadryas',           'Hamadryas Baboon'),
    ('phoenicopterus_ruber',      'American Flamingo'),
    ('pithecia_pithecia',         'White-Faced Saki'),
    ('propithecus_coquereli',     "Coquerel's Sifaka"),
    ('rhea_americana',            'Greater Rhea'),
    ('saiga_tatarica',            'Saiga'),
    ('speothos_venaticus',        'Bush Dog'),
    ('sus_scrofa',                'Wild Boar'),
    ('testudo_hermanni',          "Hermann's Tortoise"),
    ('tremarctos_ornatus',        'Spectacled Bear'),
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

    for latin_id, display_name in MISSING:
        dest = os.path.join(IMG_DIR, f'{latin_id}.png')
        if os.path.exists(dest):
            print(f'  skip  {display_name}')
            continue

        wiki_title = WIKI_TITLE_OVERRIDES.get(latin_id, display_name)
        print(f'  fetch {display_name} ("{wiki_title}") ... ', end='', flush=True)

        try:
            img_url = get_image_url_from_page(wiki_title)
            if not img_url:
                print('no image found')
                failed.append((latin_id, display_name, 'no image on page'))
                continue

            download(img_url, dest)
            print(f'ok ({os.path.getsize(dest):,} bytes)')
        except Exception as e:
            print(f'ERROR: {e}')
            failed.append((latin_id, display_name, str(e)))

        time.sleep(0.5)  # be polite to the wiki

    print()
    if failed:
        print(f'{len(failed)} failed:')
        for latin_id, name, reason in failed:
            print(f'  {name}: {reason}')
    else:
        print('All images downloaded successfully.')


if __name__ == '__main__':
    main()

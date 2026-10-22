"""Render an original terminal profile from public GitHub metadata.

Only the public user and public owner-repository REST endpoints are queried.
No commit history or private-repository endpoint is queried. Only the six
defined aggregate fields are retained; raw user/repository responses, email
addresses, and company fields are not saved. The renderer also works offline.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
USERNAME = 'AimanRosman'
API = 'https://api.github.com'
THEMES = {
    'dark': {'bg': '#0d1117', 'bar': '#161b22', 'panel': '#101820',
             'line': '#303d4b', 'text': '#e6edf3', 'muted': '#9baabc',
             'green': '#72dbb3', 'blue': '#91bdff', 'amber': '#efc188'},
    'light': {'bg': '#f8fafc', 'bar': '#edf2f7', 'panel': '#eef5f8',
              'line': '#c9d5e2', 'text': '#233348', 'muted': '#53667d',
              'green': '#087a60', 'blue': '#225aa8', 'amber': '#91560e'},
}

# Original ASCII illustration: camera input, vision processor, physical output.
ART = [
    '       .---------------.       ',
    '       |  CAMERA INPUT |       ',
    '       |    .-----.    |       ',
    '       |   (  (o)  )   |       ',
    "       '-------+-------'       ",
    '               |               ',
    '        +------+------+        ',
    '     ---|             |---     ',
    '     ---|  V I S I O N|---     ',
    '     ---|     + AI    |---     ',
    '     ---|             |---     ',
    '        +------+------+        ',
    '               |               ',
    '         .-----+-----.         ',
    '         |  CONTROL  |         ',
    "         '-----------'         ",
]


def request_json(path, token=None):
    headers = {'Accept': 'application/vnd.github+json',
               'User-Agent': 'AimanRosman-Public-Profile',
               'X-GitHub-Api-Version': '2026-03-10'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Public GitHub API request returned HTTP {error.code}') from None
    except urllib.error.URLError:
        raise RuntimeError('Could not reach the public GitHub API') from None


def collect_public_profile(token=None):
    user = request_json(f'/users/{USERNAME}', token)
    if user.get('login', '').lower() != USERNAME.lower():
        raise ValueError('Unexpected public user response')
    repositories = []
    page = 1
    while True:
        batch = request_json(f'/users/{USERNAME}/repos?type=owner&per_page=100&page={page}', token)
        for repo in batch:
            # Defense in depth: never publish a private or differently owned item.
            if repo.get('private') is not False or repo.get('owner', {}).get('login', '').lower() != USERNAME.lower():
                raise ValueError('Unexpected repository visibility or ownership')
            repositories.append(repo)
        if len(batch) < 100:
            break
        page += 1
    return validate_snapshot({
        'username': USERNAME,
        'public_repositories': len(repositories),
        'public_original_repo_stars': sum(repo['stargazers_count'] for repo in repositories if not repo['fork']),
        'followers': user['followers'],
        'account_since': user['created_at'][:4],
        'updated_utc': dt.datetime.now(dt.timezone.utc).date().isoformat(),
    })


def validate_snapshot(data):
    expected = {'username', 'public_repositories', 'public_original_repo_stars',
                'followers', 'account_since', 'updated_utc'}
    if set(data) != expected or data['username'] != USERNAME:
        raise ValueError('Snapshot must contain only the defined public profile fields')
    for key in ('public_repositories', 'public_original_repo_stars', 'followers'):
        if type(data[key]) is not int or not 0 <= data[key] <= 999_999_999:
            raise ValueError('Invalid public statistic: ' + key)
    year = data['account_since']
    if not isinstance(year, str) or len(year) != 4 or not year.isdigit():
        raise ValueError('Invalid public account creation year')
    if dt.date.fromisoformat(data['updated_utc']).isoformat() != data['updated_utc']:
        raise ValueError('Invalid snapshot date')
    return data


def number(value):
    """Fit growing counts without overflowing the stat columns."""
    if value < 10_000:
        return f'{value:,}'
    for unit, divisor in (('M', 1_000_000), ('k', 1_000)):
        if value >= divisor:
            return f'{value / divisor:.1f}'.rstrip('0').rstrip('.') + unit
    return str(value)


def render_svg(data, theme='dark', mobile=False):
    palette = THEMES[theme]
    width, height = (480, 760) if mobile else (1080, 540)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">Aiman Rosman — computer vision and embedded systems</title>',
             '<desc id="desc">Original terminal-style profile with camera and processor ASCII art. '
             'Python, C/C++, JavaScript, OpenCV, YOLO, ESP32, ESP8266, K230, Pico, PySide6, and Gemini Live. '
             f'{data["public_repositories"]} public repositories, {data["public_original_repo_stars"]} stars on original public repositories, '
             f'{data["followers"]} followers. Public metadata updated {data["updated_utc"]} UTC.</desc>',
             f'<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="14" fill="{palette["bg"]}" stroke="{palette["line"]}"/>',
             f'<path d="M15 1H{width-15}Q{width-1} 1 {width-1} 15V46H1V15Q1 1 15 1Z" fill="{palette["bar"]}"/>',
             '<g font-family="Consolas,DejaVu Sans Mono,Menlo,monospace">']

    def text(x, y, content, size=16, color='text', weight='400', extra=''):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
                     f'fill="{palette[color]}" {extra}>{escape(str(content))}</text>')

    def rule(x1, y, x2):
        parts.append(f'<path d="M{x1} {y}H{x2}" stroke="{palette["line"]}"/>')

    for x, color in ((22, '#f07878'), (41, '#e3bc67'), (60, '#70c69f')):
        parts.append(f'<circle cx="{x}" cy="24" r="5" fill="{color}"/>')
    text(83, 29, 'aiman@github:~', 13, 'muted')

    if mobile:
        text(24, 85, '$ whoami', 15, 'green')
        text(24, 124, 'Aiman Rosman', 30, 'text', '700')
        text(24, 154, 'Computer vision + embedded AI', 16, 'blue')
        rule(24, 176, 456)
        # A compact camera-to-controller emblem instead of shrinking the desktop art.
        text(28, 212, '[ CAMERA ] --> [ VISION ] --> [ I/O ]', 18, 'green', extra='xml:space="preserve"')
        rows = [('Languages', 'Python / C/C++ / JavaScript'),
                ('Vision', 'OpenCV / YOLO / face_recognition'),
                ('Boards', 'ESP32 / ESP8266 / K230 / Pico'),
                ('Apps', 'PySide6 / Gemini Live / Three.js'),
                ('Build', 'Cameras, code, physical devices'),
                ('Portfolio', 'aimanrosman.vercel.app')]
        for index, (label, value) in enumerate(rows):
            y = 253 + index * 58
            text(24, y, label + ' ........', 14, 'amber')
            text(24, y + 25, value, 17, 'text')
        rule(24, 611, 456)
        stats_y = 654
        stat_x = [25, 184, 332]
        label_y = 679
        text(24, 720, f'Public data / {data["updated_utc"]} UTC', 13, 'muted')
        text(24, 742, f'GitHub since {data["account_since"]}', 13, 'muted')
    else:
        text(915, 29, 'PUBLIC / AI + IOT', 12, 'muted')
        parts.append(f'<rect x="23" y="70" width="324" height="370" rx="8" fill="{palette["panel"]}" stroke="{palette["line"]}"/>')
        for index, line in enumerate(ART):
            text(32, 101 + index * 20, line, 16, 'green' if 6 <= index <= 11 else 'blue', extra='xml:space="preserve"')
        text(51, 425, 'CAMERA / VISION / CONTROL', 13, 'muted')
        text(382, 94, '$ whoami', 16, 'green')
        text(382, 139, 'Aiman Rosman', 34, 'text', '700')
        text(382, 170, 'Computer vision + embedded AI', 17, 'blue')
        rule(382, 191, 1048)
        rows = [('Languages', 'Python / C/C++ / JavaScript'),
                ('Vision', 'OpenCV / YOLO / face_recognition'),
                ('Boards', 'ESP32 / ESP8266 / K230 / Pico'),
                ('Apps', 'PySide6 / Gemini Live / Three.js'),
                ('Build', 'Cameras, code, physical devices'),
                ('Portfolio', 'aimanrosman.vercel.app')]
        for index, (label, value) in enumerate(rows):
            y = 226 + index * 34
            text(382, y, label, 16, 'amber')
            text(480, y, '...', 16, 'muted')
            text(524, y, value, 16, 'text')
        rule(23, 458, 1056)
        stats_y = 493
        label_y = 516
        stat_x = [37, 215, 392]
        text(660, 491, f'GitHub since {data["account_since"]}', 13, 'muted')
        text(660, 515, f'Public data / {data["updated_utc"]} UTC', 13, 'muted')

    for x, label, key in zip(stat_x, ['PUBLIC REPOS', 'ORIGINAL STARS', 'FOLLOWERS'],
                              ['public_repositories', 'public_original_repo_stars', 'followers']):
        text(x, stats_y, number(data[key]), 27, 'green', '700')
        text(x, label_y, label, 11, 'muted')
    parts.extend(['</g>', '</svg>'])
    return '\n'.join(parts) + '\n'


def write_assets(data):
    data = validate_snapshot(data)
    folder = ROOT / 'assets'
    folder.mkdir(exist_ok=True)
    for theme in THEMES:
        for mobile in (False, True):
            suffix = f'mobile-{theme}' if mobile else theme
            (folder / f'profile-terminal-{suffix}.svg').write_text(render_svg(data, theme, mobile), encoding='utf-8', newline='\n')
    (folder / 'profile-data.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Render from a saved public snapshot without network access')
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text(encoding='utf-8')) if args.snapshot else collect_public_profile(os.environ.get('GITHUB_TOKEN'))
    write_assets(data)
    print('Generated four profile SVGs from defined public metadata fields.')


if __name__ == '__main__':
    main()

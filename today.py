"""Personalize Andrew6rant's actual SVG template without changing its layout."""
import argparse
import copy
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from public_stats import collect_public_profile, validate_snapshot

ROOT = Path(__file__).resolve().parent
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def render_svg(data, theme, profile=None, portrait=None):
    data = validate_snapshot(data)
    if theme not in ('light', 'dark'):
        raise ValueError('Expected a light or dark template')
    profile = profile if profile is not None else json.loads((ROOT / 'assets/profile.json').read_text(encoding='utf-8'))
    portrait = portrait if portrait is not None else json.loads((ROOT / 'assets/portrait-ascii.json').read_text(encoding='utf-8'))
    if portrait.get('columns') != 76 or portrait.get('row_count') != 66:
        raise ValueError('Portrait must fit the template character grid')
    for rows_key in ('light_rows', 'dark_rows'):
        rows = portrait.get(rows_key)
        if not isinstance(rows, list) or len(rows) != 66:
            raise ValueError('Both themed portrait grids are required')
        if any(not isinstance(line, str) or len(line) != 76 or any(ord(char) < 32 or ord(char) > 126 for char in line) for line in rows):
            raise ValueError('Invalid portrait glyph row')
    for key in ('font_size', 'line_height', 'baseline_y', 'width'):
        if type(portrait.get(key)) not in (int, float) or not 0 < portrait[key] < 530:
            raise ValueError('Invalid portrait geometry')
    if portrait['width'] > 360 or portrait['font_size'] > portrait['line_height'] * 1.2 or portrait['baseline_y'] < portrait['font_size'] or portrait['baseline_y'] + 65 * portrait['line_height'] > 515:
        raise ValueError('Portrait exceeds the template bounds')
    root = ET.parse(ROOT / 'templates' / f'{theme}_mode.svg').getroot()
    root.set('role', 'img')
    root.set('aria-labelledby', 'title desc')
    title = ET.Element(f'{{{NS}}}title', {'id': 'title'})
    title.text = "Aiman Rosman's GitHub Profile README"
    description = ET.Element(f'{{{NS}}}desc', {'id': 'desc'})
    description.text = (f'Aiman Rosman, {profile["role"]}. ASCII portrait from his supplied photograph. '
                        f'{data["public_repositories"]} public repositories, {data["authored_commits"]} authored public commits, '
                        f'{data["followers"]} followers. Updated {data["updated_utc"]} UTC. '
                        'Lines of Code is additions minus deletions in authored public default-branch history.')
    root.insert(0, title)
    root.insert(1, description)
    texts = root.findall(f'{{{NS}}}text')
    art, details = texts
    for child in list(art):
        art.remove(child)
    art.text = '\n'
    for index, line in enumerate(portrait[theme + '_rows']):
        span = ET.SubElement(art, f'{{{NS}}}tspan', {
            'x': '15', 'y': f'{portrait["baseline_y"] + index * portrait["line_height"]:.6f}',
            'font-size': str(portrait['font_size']), 'font-weight': '700',
            'textLength': str(portrait['width']), 'lengthAdjust': 'spacingAndGlyphs',
        })
        span.text = line
        span.tail = '\n'

    # Keep the upstream statistics markup, spacing parameters, and element IDs.
    stats = []
    current_y = 0
    for child in details:
        if 'y' in child.attrib:
            current_y = int(child.attrib['y'])
        if current_y >= 450:
            stats.append(copy.deepcopy(child))
    for child in list(details):
        details.remove(child)
    details.text = '\n'

    def span(value, *, y=None, css=None):
        attributes = {}
        if y is not None:
            attributes.update({'x': '390', 'y': str(y)})
        if css:
            attributes['class'] = css
        element = ET.SubElement(details, f'{{{NS}}}tspan', attributes)
        element.text = value
        return element

    heading = span(profile['handle'], y=30)
    heading.tail = ' ' + '—' * (59 - len(profile['handle'])) + '\n'

    def row(y, label, value):
        if not isinstance(value, str) or '\n' in value:
            raise ValueError('Expected a single-line public profile value')
        prefix = span('. ', y=y, css='cc')
        keys = label.split('.')
        for index, key in enumerate(keys):
            item = span(key, css='key')
            item.tail = '.' if index < len(keys) - 1 else ':'
        padding = 60 - (2 + len(label) + 1 + len(value) + 2)
        fit_kernel = padding < 1 and label == 'Kernel' and len(value) <= 60
        if padding < 1 and not fit_kernel:
            raise ValueError('Profile field exceeds the template width: ' + label)
        span(' ' if fit_kernel else ' ' + '.' * padding + ' ', css='cc')
        item = span(value, css='value')
        if fit_kernel:
            # Preserve the full title on one row within the existing card.
            item.set('x', '490')
            item.set('textLength', '480')
            item.set('lengthAdjust', 'spacingAndGlyphs')
        item.tail = '\n'

    for y, label, key in (
        (50, 'OS', 'os'), (70, 'Uptime', 'age'), (90, 'Host', 'host'),
        (110, 'Kernel', 'role'), (130, 'IDE', 'ide'),
        (170, 'Languages.Programming', 'programming'),
        (190, 'Languages.Computer', 'computer_languages'),
        (210, 'Languages.Real', 'spoken_languages'),
        (250, 'Hobbies.Software', 'software_hobbies'),
        (270, 'Hobbies.Other', 'hardware_hobbies'),
        (330, 'Website.Personal', 'portfolio'),
        (350, 'GitHub', 'github'), (370, 'Location', 'location'),
        (390, 'LinkedIn', 'linkedin'), (410, 'Contact', 'contact'),
    ):
        if y == 330:
            section = span('- Contact', y=310)
            section.tail = ' ' + '—' * 50 + '\n'
        row(y, label, profile[key])
    for element in stats:
        details.append(element)

    def replace(identifier, value):
        element = root.find(f".//*[@id='{identifier}']")
        if element is None:
            raise ValueError('Expected upstream statistics field: ' + identifier)
        element.text = str(value)

    def justify(identifier, value, width=0):
        value = f'{value:,}'
        replace(identifier, value)
        count = max(0, width - len(value))
        dots = {0: '', 1: ' ', 2: '. '}.get(count, ' ' + '.' * count + ' ')
        if root.find(f".//*[@id='{identifier}_dots']") is not None:
            replace(identifier + '_dots', dots)

    for identifier, key, width in (
        ('commit_data', 'authored_commits', 22),
        ('star_data', 'public_original_repo_stars', 14),
        ('repo_data', 'public_repositories', 6),
        ('contrib_data', 'contributed_repositories', 0),
        ('follower_data', 'followers', 10),
        ('loc_data', 'net_lines', 9),
        ('loc_add', 'additions', 0), ('loc_del', 'deletions', 7),
    ):
        justify(identifier, data[key], width)
    # Correct the upstream label's spelling while retaining its same span.
    for element in details:
        if element.text == 'Commmits':
            element.text = 'Commits'
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'


def write_assets(data):
    data = validate_snapshot(data)
    outputs = {f'{theme}_mode.svg': render_svg(data, theme) for theme in ('light', 'dark')}
    outputs['assets/profile-data.json'] = json.dumps(data, indent=2) + '\n'
    for path, content in outputs.items():
        destination = ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Render a saved public aggregate snapshot offline')
    arguments = parser.parse_args()
    data = json.loads(arguments.snapshot.read_text(encoding='utf-8')) if arguments.snapshot else collect_public_profile(os.environ.get('GITHUB_TOKEN'))
    write_assets(data)
    print('Updated the actual light/dark templates with personalized public profile data.')


if __name__ == '__main__':
    main()

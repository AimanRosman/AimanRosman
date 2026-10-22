"""Verify actual-template fidelity and the single-image profile output."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
SPEC = importlib.util.spec_from_file_location('exact_profile_under_test', PROJECT / 'today.py')
today = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(today)
NS = '{http://www.w3.org/2000/svg}'


def snapshot():
    return {'username': 'AimanRosman', 'public_repositories': 16,
            'public_original_repo_stars': 4, 'followers': 10,
            'account_since': '2024', 'updated_utc': '2026-10-22',
            'authored_commits': 125, 'contributed_repositories': 14,
            'additions': 20000, 'deletions': 5000, 'net_lines': 15000}


class ActualTemplateTests(unittest.TestCase):
    def test_upstream_dimensions_fonts_palettes_and_row_positions_are_preserved(self):
        for theme in ('light', 'dark'):
            with self.subTest(theme=theme):
                original = ET.parse(PROJECT / 'templates' / f'{theme}_mode.svg').getroot()
                rendered = ET.fromstring(today.render_svg(snapshot(), theme))
                for key, value in original.attrib.items():
                    self.assertEqual(rendered.attrib[key], value)
                self.assertEqual(rendered.find(NS + 'style').text, original.find(NS + 'style').text)
                self.assertEqual(rendered.find(NS + 'rect').attrib, original.find(NS + 'rect').attrib)
                art, rows = rendered.findall(NS + 'text')
                self.assertEqual(art.attrib, original.findall(NS + 'text')[0].attrib)
                self.assertEqual([line.attrib['y'] for line in art], [str(30 + index * 20) for index in range(25)])
                self.assertEqual(rows.attrib, original.findall(NS + 'text')[1].attrib)
                y_values = {element.attrib.get('y') for element in rows}
                self.assertTrue({'30', '50', '70', '90', '110', '130', '170', '190', '210', '250', '270', '310', '330', '350', '370', '390', '410', '450', '470', '490', '510'}.issubset(y_values))

    def test_only_supplied_identity_and_actual_portrait_reach_the_output(self):
        portrait = json.loads((PROJECT / 'assets/portrait-ascii.json').read_text(encoding='utf-8'))
        for theme in ('light', 'dark'):
            root = ET.fromstring(today.render_svg(snapshot(), theme))
            content = ''.join(root.itertext())
            for expected in ('aiman@rosman', '23 years', 'AI & IoT Manager', 'Mandarin, English, Malay'):
                self.assertIn(expected, content)
            for stale in ('Andrew Grant', 'andrew@grant', 'TTM Technologies', 'Minecraft Modding', 'CAMERA INPUT', 'PUBLIC / AI + IOT'):
                self.assertNotIn(stale, content)
            self.assertEqual([element.text for element in root.findall(NS + 'text')[0]], portrait['rows'])

    def test_upstream_dynamic_ids_display_the_aggregate_snapshot(self):
        root = ET.fromstring(today.render_svg(snapshot(), 'light'))
        expected = {'repo_data': '16', 'contrib_data': '14', 'star_data': '4',
                    'commit_data': '125', 'follower_data': '10',
                    'loc_data': '15,000', 'loc_add': '20,000', 'loc_del': '5,000'}
        for identifier, value in expected.items():
            self.assertEqual(root.find(f".//*[@id='{identifier}']").text, value)

    def test_card_is_accessible_native_text_with_no_external_or_executable_content(self):
        for theme in ('light', 'dark'):
            root = ET.fromstring(today.render_svg(snapshot(), theme))
            for identifier in root.attrib['aria-labelledby'].split():
                self.assertIsNotNone(root.find(f".//*[@id='{identifier}']"))
            for element in root.iter():
                self.assertNotIn(element.tag, (NS + 'image', NS + 'script', NS + 'foreignObject'))
                self.assertFalse(any(key.lower().startswith('on') or key.endswith('href') for key in element.attrib))

    def test_invalid_portrait_and_overlong_fields_fail_before_publication(self):
        profile = json.loads((PROJECT / 'assets/profile.json').read_text(encoding='utf-8'))
        profile['role'] = 'A' * 200
        with self.assertRaisesRegex(ValueError, 'template width'):
            today.render_svg(snapshot(), 'light', profile=profile)
        with self.assertRaisesRegex(ValueError, 'character grid'):
            today.render_svg(snapshot(), 'light', portrait={'columns': 500, 'rows': []})

    def test_write_uses_only_two_root_svgs_and_the_aggregate_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory)
            shutil.copytree(PROJECT / 'templates', draft / 'templates')
            (draft / 'assets').mkdir()
            for name in ('profile.json', 'portrait-ascii.json'):
                shutil.copyfile(PROJECT / 'assets' / name, draft / 'assets' / name)
            with patch.object(today, 'ROOT', draft):
                today.write_assets(snapshot())
            paths = {path.relative_to(draft).as_posix() for path in draft.rglob('*') if path.is_file()}
            self.assertEqual(paths, {'templates/light_mode.svg', 'templates/dark_mode.svg',
                                     'assets/profile.json', 'assets/portrait-ascii.json',
                                     'assets/profile-data.json', 'light_mode.svg', 'dark_mode.svg'})

    def test_readme_is_only_the_same_linked_picture_structure_as_upstream(self):
        readme = (PROJECT / 'README.md').read_text(encoding='utf-8')
        self.assertEqual(len(readme.splitlines()), 6)
        self.assertEqual(readme.count('<picture>'), 1)
        self.assertEqual(readme.count('<source '), 1)
        self.assertEqual(readme.count('<img '), 1)
        for removed in ('<details>', '<summary>', '## ', 'Pac-Man', 'Featured:'):
            self.assertNotIn(removed, readme)


if __name__ == '__main__':
    unittest.main()

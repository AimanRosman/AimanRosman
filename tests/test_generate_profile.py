"""Public-data and output-boundary checks; no GitHub requests are performed."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'terminal_profile_generator_under_test', PROJECT / 'scripts' / 'generate_profile.py'
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)

PUBLIC_FIELDS = {
    'username', 'public_repositories', 'public_original_repo_stars',
    'followers', 'account_since', 'updated_utc',
}
OUTPUT_NAMES = {
    'profile-data.json',
    'profile-terminal-dark.svg', 'profile-terminal-light.svg',
    'profile-terminal-mobile-dark.svg', 'profile-terminal-mobile-light.svg',
}
UNPUBLISHED = 'SYNTHETIC_METADATA_MUST_NOT_APPEAR_IN_ASSETS'


def public_user(**changes):
    value = {
        'login': 'AimanRosman', 'followers': 12,
        'created_at': '2024-03-04T05:06:07Z',
        # Collection must count the returned public repositories, not trust a
        # conflicting account count or retain unrelated response metadata.
        'public_repos': 987, 'email': UNPUBLISHED, 'company': UNPUBLISHED,
    }
    value.update(changes)
    return value


def public_repo(name='sample', stars=1, fork=False, **changes):
    value = {
        'name': name, 'private': False,
        'owner': {'login': 'AimanRosman', 'email': UNPUBLISHED},
        'stargazers_count': stars, 'fork': fork,
        'description': UNPUBLISHED,
    }
    value.update(changes)
    return value


def valid_snapshot(**changes):
    value = {
        'username': 'AimanRosman', 'public_repositories': 16,
        'public_original_repo_stars': 4, 'followers': 12,
        'account_since': '2024', 'updated_utc': '2026-10-22',
    }
    value.update(changes)
    return value


class PublicCollectionTests(unittest.TestCase):
    def setUp(self):
        # A future accidental call that bypasses the mocked request helper must
        # fail, rather than contact GitHub or use a developer's environment.
        network = patch.object(
            generator.urllib.request, 'urlopen',
            side_effect=AssertionError('Network access is forbidden in these tests'),
        )
        network.start()
        self.addCleanup(network.stop)

    def collect(self, pages, user=None):
        responses = [public_user() if user is None else user, *pages]
        with patch.object(generator, 'request_json', side_effect=copy.deepcopy(responses)) as request:
            result = generator.collect_public_profile()
        return result, [call.args[0] for call in request.call_args_list]

    def test_counts_all_public_owned_repos_but_only_original_stars_across_pages(self):
        first = [public_repo(f'original-{i}', stars=2) for i in range(60)]
        first += [public_repo(f'fork-{i}', stars=1000, fork=True) for i in range(40)]
        second = [public_repo('last-original', stars=5),
                  public_repo('last-fork', stars=9000, fork=True),
                  public_repo('zero-star-original', stars=0)]

        result, paths = self.collect([first, second])

        self.assertEqual(result['public_repositories'], 103)
        self.assertEqual(result['public_original_repo_stars'], 125)
        self.assertEqual(result['followers'], 12)
        self.assertEqual(result['account_since'], '2024')
        self.assertEqual(paths, [
            '/users/AimanRosman',
            '/users/AimanRosman/repos?type=owner&per_page=100&page=1',
            '/users/AimanRosman/repos?type=owner&per_page=100&page=2',
        ])

    def test_exact_full_page_fetches_empty_next_page_before_stopping(self):
        result, paths = self.collect([
            [public_repo(f'fork-{i}', stars=500, fork=True) for i in range(100)],
            [],
        ])
        self.assertEqual(result['public_repositories'], 100)
        self.assertEqual(result['public_original_repo_stars'], 0)
        self.assertEqual(len(paths), 3)
        self.assertTrue(paths[-1].endswith('page=2'))

    def test_empty_public_inventory_is_a_valid_zero_count(self):
        result, paths = self.collect([[]])
        self.assertEqual(result['public_repositories'], 0)
        self.assertEqual(result['public_original_repo_stars'], 0)
        self.assertEqual(len(paths), 2)

    def test_private_or_unconfirmed_visibility_fails_closed(self):
        for visibility in (True, None, 'false', 0):
            with self.subTest(visibility=visibility):
                with self.assertRaises(ValueError):
                    self.collect([[public_repo(private=visibility)]])
        missing = public_repo()
        del missing['private']
        with self.assertRaises(ValueError):
            self.collect([[missing]])

    def test_other_owner_and_missing_owner_fail_closed(self):
        for owner in ({'login': 'AnotherAccount'}, {}, None):
            with self.subTest(owner=owner):
                # An explicit null owner is malformed API data as well. Either
                # rejection form must occur before a snapshot can be returned.
                with self.assertRaises((ValueError, AttributeError)):
                    self.collect([[public_repo(owner=owner)]])
        missing = public_repo()
        del missing['owner']
        with self.assertRaises(ValueError):
            self.collect([[missing]])

    def test_private_item_on_later_page_cannot_be_hidden_by_public_first_page(self):
        first = [public_repo(f'original-{i}') for i in range(100)]
        with self.assertRaises(ValueError):
            self.collect([first, [public_repo('not-public', private=True)]])

    def test_unexpected_user_is_rejected_before_repository_collection(self):
        with patch.object(generator, 'request_json', return_value=public_user(login='AnotherAccount')) as request:
            with self.assertRaises(ValueError):
                generator.collect_public_profile()
        self.assertEqual(request.call_count, 1)

    def test_github_login_matching_is_case_insensitive(self):
        result, _ = self.collect(
            [[public_repo(owner={'login': 'aimanrosman'})]],
            user=public_user(login='AIMANROSMAN'),
        )
        self.assertEqual(result['username'], 'AimanRosman')
        self.assertEqual(result['public_repositories'], 1)

    def test_unrelated_api_metadata_never_reaches_snapshot_or_assets(self):
        result, _ = self.collect([[public_repo(stars=7)]])
        self.assertEqual(set(result), PUBLIC_FIELDS)
        self.assertNotIn(UNPUBLISHED, json.dumps(result))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(generator, 'ROOT', Path(directory)):
                generator.write_assets(result)
            assets = Path(directory) / 'assets'
            self.assertEqual({path.name for path in assets.iterdir()}, OUTPUT_NAMES)
            stored = json.loads((assets / 'profile-data.json').read_text(encoding='utf-8'))
            self.assertEqual(stored, result)
            for path in assets.iterdir():
                self.assertNotIn(UNPUBLISHED, path.read_text(encoding='utf-8'))


class SnapshotBoundaryTests(unittest.TestCase):
    def test_extra_snapshot_fields_are_rejected_before_any_asset_write(self):
        for field in ('email', 'company', 'private_repositories', 'repositories', 'public_gists'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                data = valid_snapshot(**{field: {'unpublished': UNPUBLISHED}})
                with patch.object(generator, 'ROOT', Path(directory)):
                    with self.assertRaises(ValueError):
                        generator.write_assets(data)
                self.assertFalse((Path(directory) / 'assets').exists())

    def test_invalid_snapshot_does_not_overwrite_previously_valid_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(generator, 'ROOT', Path(directory)):
                generator.write_assets(valid_snapshot())
                assets = Path(directory) / 'assets'
                before = {path.name: path.read_bytes() for path in assets.iterdir()}
                with self.assertRaises(ValueError):
                    generator.write_assets(valid_snapshot(email=UNPUBLISHED))
                after = {path.name: path.read_bytes() for path in assets.iterdir()}
                self.assertEqual(after, before)

    def test_missing_snapshot_fields_and_other_username_are_rejected(self):
        for field in PUBLIC_FIELDS:
            with self.subTest(missing=field):
                data = valid_snapshot()
                del data[field]
                with self.assertRaises(ValueError):
                    generator.validate_snapshot(data)
        with self.assertRaises(ValueError):
            generator.validate_snapshot(valid_snapshot(username='AnotherAccount'))

    def test_statistics_require_bounded_integers_and_reject_booleans(self):
        for field in ('public_repositories', 'public_original_repo_stars', 'followers'):
            for value in (True, False, -1, 1.5, '12', 1_000_000_000):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        generator.validate_snapshot(valid_snapshot(**{field: value}))

    def test_invalid_dates_and_markup_in_date_fields_are_rejected(self):
        for value in ('2026-02-30', '20261022', '<script>synthetic</script>'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    generator.validate_snapshot(valid_snapshot(updated_utc=value))
        with self.assertRaises(ValueError):
            generator.validate_snapshot(valid_snapshot(account_since='<2024>'))

    def test_snapshot_cli_stays_offline_and_generates_only_allowlisted_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'input.json'
            snapshot.write_text(json.dumps(valid_snapshot()), encoding='utf-8')
            with patch.object(generator, 'ROOT', Path(directory)), \
                 patch.object(generator, 'collect_public_profile', side_effect=AssertionError('Snapshot mode must stay offline')) as collect, \
                 patch('sys.argv', ['generate_profile.py', '--snapshot', str(snapshot)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                generator.main()
            collect.assert_not_called()
            self.assertEqual(
                {path.name for path in (Path(directory) / 'assets').iterdir()},
                OUTPUT_NAMES,
            )


class SvgOutputTests(unittest.TestCase):
    def test_zero_and_maximum_stats_produce_valid_accessible_static_svg_variants(self):
        namespace = '{http://www.w3.org/2000/svg}'
        for count in (0, 999_999_999):
            for theme in ('dark', 'light'):
                for mobile in (False, True):
                    with self.subTest(count=count, theme=theme, mobile=mobile):
                        data = valid_snapshot(
                            public_repositories=count,
                            public_original_repo_stars=count,
                            followers=count,
                        )
                        root = ET.fromstring(generator.render_svg(data, theme, mobile))
                        self.assertEqual(root.tag, namespace + 'svg')
                        self.assertGreater(int(root.attrib['width']), 0)
                        self.assertGreater(int(root.attrib['height']), 0)
                        ids = {element.attrib.get('id') for element in root.iter()}
                        for identifier in root.attrib['aria-labelledby'].split():
                            self.assertIn(identifier, ids)
                        description = root.find(namespace + 'desc').text
                        self.assertIn(f'{count} public repositories', description)
                        self.assertIn(f'{count} stars on original public repositories', description)
                        self.assertIn('2026-10-22 UTC', description)
                        for element in root.iter():
                            self.assertNotIn(element.tag, (namespace + 'script', namespace + 'foreignObject'))
                            self.assertFalse(any(key.lower().startswith('on') for key in element.attrib))


if __name__ == '__main__':
    unittest.main()

"""Mocked public-only collection tests: no tokens, network, or private data."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error


SPEC = importlib.util.spec_from_file_location(
    'exact_profile_public_stats_under_test',
    Path(__file__).resolve().parents[1] / 'public_stats.py',
)
stats = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stats)

USER_ID = 'SYNTHETIC_PUBLIC_USER_ID'
EXCLUDED = 'SYNTHETIC_RESPONSE_METADATA_NOT_FOR_PUBLICATION'
FIELDS = {
    'username', 'public_repositories', 'public_original_repo_stars', 'followers',
    'account_since', 'updated_utc', 'authored_commits', 'contributed_repositories',
    'additions', 'deletions', 'net_lines',
}


def oid(number):
    return f'{number:040x}'


def user(**changes):
    value = {'login': 'AimanRosman', 'node_id': USER_ID, 'followers': 10,
             'created_at': '2024-02-03T04:05:06Z', 'email': EXCLUDED,
             'public_repos': 900, 'company': EXCLUDED}
    value.update(changes)
    return value


def repo(name='project', stars=1, fork=False, **changes):
    value = {'name': name, 'private': False, 'owner': {'login': 'AimanRosman'},
             'fork': fork, 'stargazers_count': stars, 'description': EXCLUDED}
    value.update(changes)
    return value


def commit(number, additions=10, deletions=2, author=USER_ID):
    return {'oid': oid(number), 'additions': additions, 'deletions': deletions,
            'author': {'user': {'id': author} if author else None}}


def history(nodes=(), *, tip=900, more=False, cursor=None, pinned=False, **changes):
    value = {'isPrivate': False, 'owner': {'login': 'AimanRosman'}}
    target = {'__typename': 'Commit', 'oid': oid(tip),
              'history': {'nodes': list(nodes),
                          'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}}
    value['object' if pinned else 'defaultBranchRef'] = target if pinned else {'target': target}
    value.update(changes)
    return value


def empty_repo():
    return {'isPrivate': False, 'owner': {'login': 'AimanRosman'}, 'defaultBranchRef': None}


def response(*repositories):
    return {'data': {f'r{i}': repo for i, repo in enumerate(repositories)}}


def snapshot(**changes):
    value = {'username': 'AimanRosman', 'public_repositories': 2,
             'public_original_repo_stars': 3, 'followers': 10,
             'account_since': '2024', 'updated_utc': '2026-10-22',
             'authored_commits': 1, 'contributed_repositories': 1,
             'additions': 1, 'deletions': 4, 'net_lines': -3}
    value.update(changes)
    return value


class CollectionTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(stats.urllib.request, 'urlopen',
                               side_effect=AssertionError('Tests must not contact GitHub'))
        network.start()
        self.addCleanup(network.stop)

    def collect(self, responses):
        with patch.object(stats, '_request_json', side_effect=copy.deepcopy(responses)) as request:
            value = stats.collect_public_profile('synthetic-test-token')
        return value, request.call_args_list

    def test_pagination_primary_author_and_global_oid_deduplication(self):
        original = history([commit(1), commit(1), commit(50, author='another-user')],
                           more=True, cursor='next-original')
        fork = history([commit(1), commit(2, 1, 4)], tip=901)
        second_page = history([commit(2, 1, 4), commit(3, 0, 8)], pinned=True)
        value, calls = self.collect([
            user(), [repo('original', 3), repo('fork', 400, True), repo('empty', 2)],
            response(original, fork, empty_repo()), response(second_page),
        ])
        self.assertEqual(set(value), FIELDS)
        self.assertEqual(value['public_repositories'], 3)
        self.assertEqual(value['public_original_repo_stars'], 5)
        self.assertEqual(value['authored_commits'], 3)
        self.assertEqual(value['contributed_repositories'], 2)
        self.assertEqual((value['additions'], value['deletions'], value['net_lines']), (11, 14, -3))
        self.assertNotIn(EXCLUDED, json.dumps(value))
        self.assertEqual(calls[0].args[0], '/users/AimanRosman')
        self.assertEqual(calls[1].args[0], '/users/AimanRosman/repos?type=owner&per_page=100&page=1')
        first_body, next_body = calls[2].args[2], calls[3].args[2]
        self.assertEqual(first_body['variables'], {'author': USER_ID})
        self.assertIn('author: {id: $author}', first_body['query'])
        self.assertIn('author { user { id } }', first_body['query'])
        self.assertIn('object(oid: "' + oid(900) + '")', next_body['query'])
        self.assertIn('after: "next-original"', next_body['query'])
        self.assertNotIn('defaultBranchRef', next_body['query'])
        self.assertNotIn('name: "fork"', next_body['query'])
        self.assertNotIn('name: "empty"', next_body['query'])
        self.assertNotIn('/user/repos', [call.args[0] for call in calls])

    def test_one_shared_commit_can_contribute_to_two_repos(self):
        shared = commit(171)
        uppercase = dict(shared, oid=shared['oid'].upper())
        value, _ = self.collect([user(), [repo('one'), repo('two')],
                                 response(history([shared]), history([uppercase]))])
        self.assertEqual(value['authored_commits'], 1)
        self.assertEqual(value['contributed_repositories'], 2)
        self.assertEqual((value['additions'], value['deletions']), (10, 2))

    def test_explicit_repository_batches_are_bounded(self):
        value, calls = self.collect([
            user(), [repo(f'project-{i}') for i in range(7)],
            response(*[empty_repo() for _ in range(5)]),
            response(empty_repo(), empty_repo()),
        ])
        graph_queries = [call.args[2]['query'] for call in calls if call.args[0] == '/graphql']
        self.assertEqual(len(graph_queries), 2)
        self.assertEqual(graph_queries[0].count('repository(owner:'), 5)
        self.assertEqual(graph_queries[1].count('repository(owner:'), 2)
        self.assertTrue(all('owner: "AimanRosman"' in query for query in graph_queries))
        self.assertTrue(all('repositories(' not in query for query in graph_queries))
        self.assertEqual(value['public_repositories'], 7)

    def test_rest_public_inventory_paginates_and_counts_forks(self):
        replies = [user(), [repo(f'project-{i}') for i in range(100)],
                   [repo('final-fork', stars=800, fork=True)]]
        replies += [response(*[empty_repo() for _ in range(5)]) for _ in range(20)]
        replies += [response(empty_repo())]
        value, calls = self.collect(replies)
        self.assertEqual(value['public_repositories'], 101)
        self.assertEqual(value['public_original_repo_stars'], 100)
        self.assertTrue(calls[2].args[0].endswith('page=2'))

    def test_private_unconfirmed_and_wrong_owner_rest_items_are_rejected(self):
        invalid = [repo(private=True), repo(private=None), repo(private=0),
                   repo(owner={'login': 'another-user'}), repo(owner={})]
        missing = repo()
        del missing['private']
        invalid.append(missing)
        for item in invalid:
            with self.subTest(item=item):
                with patch.object(stats, '_request_json', side_effect=[user(), [item]]) as request:
                    with self.assertRaises(ValueError):
                        stats.collect_public_profile('synthetic-test-token')
                self.assertEqual(request.call_count, 2)

    def test_unexpected_user_is_rejected_before_listing_repositories(self):
        with patch.object(stats, '_request_json', return_value=user(login='another-user')) as request:
            with self.assertRaises(ValueError):
                stats.collect_public_profile('synthetic-test-token')
        self.assertEqual(request.call_count, 1)

    def test_graphql_visibility_and_owner_are_checked_again(self):
        for item in (history(isPrivate=True), history(isPrivate=None),
                     history(owner={'login': 'another-user'}), None):
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    self.collect([user(), [repo()], response(item)])

    def test_empty_and_noncommit_default_branch_targets_are_zero(self):
        noncommit = empty_repo()
        noncommit['defaultBranchRef'] = {'target': {'__typename': 'Tag', 'oid': oid(999)}}
        value, _ = self.collect([user(), [repo('empty'), repo('noncommit')],
                                 response(empty_repo(), noncommit)])
        self.assertEqual(value['authored_commits'], 0)
        self.assertEqual(value['contributed_repositories'], 0)
        self.assertEqual((value['additions'], value['deletions'], value['net_lines']), (0, 0, 0))

    def test_no_repositories_requires_no_graphql(self):
        value, calls = self.collect([user(), []])
        self.assertEqual(value['public_repositories'], 0)
        self.assertEqual(value['authored_commits'], 0)
        self.assertEqual(len(calls), 2)

    def test_coauthor_only_or_unassociated_primary_author_is_not_counted(self):
        value, _ = self.collect([user(), [repo()],
                                 response(history([commit(1, author='different-id'),
                                                   commit(2, author=None)]))])
        self.assertEqual(value['authored_commits'], 0)
        self.assertEqual(value['additions'], 0)

    def test_partial_graphql_errors_are_sanitized_not_published_as_zero(self):
        with self.assertRaises(RuntimeError) as error:
            self.collect([user(), [repo()], {'data': {'r0': history()},
                                           'errors': [{'message': EXCLUDED}]}])
        self.assertNotIn(EXCLUDED, str(error.exception))

    def test_repeated_cursor_conflicting_stats_and_tip_changes_fail(self):
        cases = [
            (history([commit(1)], more=True, cursor='same'),
             history([commit(2)], more=True, cursor='same', pinned=True)),
            (history([commit(1)], more=True, cursor='next'),
             history([commit(1, additions=999)], pinned=True)),
            (history([commit(1)], more=True, cursor='next'),
             history([commit(2)], tip=901, pinned=True)),
        ]
        for first, second in cases:
            with self.subTest(second=second):
                with self.assertRaises(ValueError):
                    self.collect([user(), [repo()], response(first), response(second)])

    def test_request_budget_fails_instead_of_returning_partial_statistics(self):
        with patch.object(stats, 'MAX_REQUESTS', 2), \
             patch.object(stats, '_request_json', side_effect=[user(), [repo()]]) as request:
            with self.assertRaises(RuntimeError):
                stats.collect_public_profile('synthetic-test-token')
        self.assertEqual(request.call_count, 2)


class SnapshotTests(unittest.TestCase):
    def test_signed_net_lines_and_shared_commit_counts_are_allowed(self):
        self.assertEqual(stats.validate_snapshot(snapshot())['net_lines'], -3)
        shared = snapshot(contributed_repositories=2, authored_commits=1)
        self.assertEqual(stats.validate_snapshot(shared)['contributed_repositories'], 2)

    def test_extra_missing_and_wrong_user_fields_fail(self):
        for key in ('email', 'company', 'private_repositories', 'commits'):
            with self.subTest(extra=key):
                with self.assertRaises(ValueError):
                    stats.validate_snapshot(snapshot(**{key: EXCLUDED}))
        for key in FIELDS:
            data = snapshot()
            del data[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                stats.validate_snapshot(data)
        with self.assertRaises(ValueError):
            stats.validate_snapshot(snapshot(username='another-user'))

    def test_snapshot_counters_and_cross_field_consistency(self):
        bad = [snapshot(net_lines=1), snapshot(contributed_repositories=3),
               snapshot(authored_commits=0), snapshot(contributed_repositories=0),
               snapshot(additions=True), snapshot(deletions=-1),
               snapshot(followers=1.5), snapshot(authored_commits=stats.MAX_STAT + 1),
               snapshot(account_since='2027'), snapshot(updated_utc='2026-02-30'),
               snapshot(updated_utc='<svg>'), snapshot(account_since='２０２４')]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                stats.validate_snapshot(data)


class TransportTests(unittest.TestCase):
    def test_http_error_discards_reason_body_and_credentials(self):
        failure = urllib.error.HTTPError('https://api.github.com/graphql', 403,
                                         EXCLUDED, {'X-Synthetic': EXCLUDED},
                                         io.BytesIO(EXCLUDED.encode()))
        with patch.object(stats.urllib.request, 'urlopen', side_effect=failure):
            with self.assertRaises(RuntimeError) as error:
                stats._request_json('/graphql', 'synthetic-test-token', {'query': '{}'})
        self.assertIn('403', str(error.exception))
        self.assertNotIn(EXCLUDED, str(error.exception))
        self.assertNotIn('synthetic-test-token', str(error.exception))

    def test_bad_json_and_network_errors_are_sanitized(self):
        with patch.object(stats.urllib.request, 'urlopen', return_value=io.BytesIO(b'not JSON')):
            with self.assertRaises(RuntimeError) as error:
                stats._request_json('/users/AimanRosman')
        self.assertNotIn('not JSON', str(error.exception))
        with patch.object(stats.urllib.request, 'urlopen', side_effect=urllib.error.URLError(EXCLUDED)):
            with self.assertRaises(RuntimeError) as error:
                stats._request_json('/users/AimanRosman')
        self.assertNotIn(EXCLUDED, str(error.exception))

    def test_builtin_or_gcm_style_token_is_only_an_authorization_header(self):
        with patch.object(stats.urllib.request, 'urlopen', return_value=io.BytesIO(b'{}')) as request:
            stats._request_json('/graphql', 'synthetic-test-token', {'query': '{}'})
        outgoing = request.call_args.args[0]
        self.assertEqual(outgoing.full_url, 'https://api.github.com/graphql')
        self.assertEqual(outgoing.get_header('Authorization'), 'Bearer synthetic-test-token')
        self.assertNotIn('synthetic-test-token', outgoing.data.decode())


if __name__ == '__main__':
    unittest.main()

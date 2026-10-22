"""Collect only public owner-repository statistics for AimanRosman's profile.

Repos includes owned public forks; stars excludes forks. Contributed repos means
owned public repositories whose default-branch history contains a commit with
this account as its primary GitHub-associated author. Commits and line totals
are deduplicated globally by OID, including merges, across those histories.
Additions/deletions include documentation, imports, and generated-file churn;
net_lines is their signed difference, not current source LOC or original
authorship. No collaborator/organization inventory, private endpoint, commit
messages, file contents, author emails, or user email fields are requested by
GraphQL or retained in the snapshot. REST responses are reduced to these fields.

First history pages capture branch tips; further pages use those immutable OIDs.
Only explicitly allowlisted repository names are queried. Authentication accepts
an explicitly supplied API token or the workflow's read-only GITHUB_TOKEN.
The caller must retain its prior dated snapshot if collection fails.
"""

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request


USERNAME = 'AimanRosman'
API = 'https://api.github.com'
BATCH_SIZE = 5
MAX_STAT = 999_999_999
MAX_REQUESTS = 100
FIELDS = frozenset({
    'username', 'public_repositories', 'public_original_repo_stars', 'followers',
    'account_since', 'updated_utc', 'authored_commits', 'contributed_repositories',
    'additions', 'deletions', 'net_lines',
})
COUNTERS = (
    'public_repositories', 'public_original_repo_stars', 'followers',
    'authored_commits', 'contributed_repositories', 'additions', 'deletions',
)
OID = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z')


def _counter(value):
    if type(value) is not int or not 0 <= value <= MAX_STAT:
        raise ValueError('Invalid public statistic')
    return value


def validate_snapshot(data):
    """Reject extra fields and inconsistent counters before rendering/publishing."""
    if not isinstance(data, dict) or set(data) != FIELDS or data.get('username') != USERNAME:
        raise ValueError('Snapshot must contain exactly the defined public fields')
    for key in COUNTERS:
        _counter(data[key])
    if type(data['net_lines']) is not int or not -MAX_STAT <= data['net_lines'] <= MAX_STAT:
        raise ValueError('Invalid net line statistic')
    if data['net_lines'] != data['additions'] - data['deletions']:
        raise ValueError('Inconsistent line statistics')
    if data['contributed_repositories'] > data['public_repositories']:
        raise ValueError('Inconsistent repository statistics')
    # One shared commit can contribute to several owned repositories, so the
    # contributed-repository count may exceed the global unique commit count.
    if bool(data['contributed_repositories']) != bool(data['authored_commits']):
        raise ValueError('Inconsistent contribution statistics')
    if not data['authored_commits'] and (data['additions'] or data['deletions']):
        raise ValueError('Line statistics require authored commits')
    if not data['public_repositories'] and data['public_original_repo_stars']:
        raise ValueError('Stars require public repositories')
    year, updated = data['account_since'], data['updated_utc']
    if not isinstance(year, str) or re.fullmatch(r'[0-9]{4}', year) is None:
        raise ValueError('Invalid account year')
    if not isinstance(updated, str):
        raise ValueError('Invalid snapshot date')
    try:
        date = dt.date.fromisoformat(updated)
        if date.isoformat() != updated or not 1 <= int(year) <= date.year:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Invalid account year or snapshot date') from None
    return dict(data)


def _request_json(path, token=None, body=None):
    """Make a fixed-origin API request; errors never include response bodies."""
    if token is not None and (not isinstance(token, str) or '\r' in token or '\n' in token):
        raise ValueError('Invalid API credential format')
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'AimanRosman-Public-Profile',
        'X-GitHub-Api-Version': '2026-03-10',
    }
    if token:
        headers['Authorization'] = 'Bearer ' + token
    payload = None
    if body is not None:
        payload = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(API + path, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Public GitHub request failed (HTTP {error.code})') from None
    except (OSError, ValueError):
        raise RuntimeError('Public GitHub API response was unavailable or invalid') from None


def _owned_public(repo, private_key):
    if not isinstance(repo, dict) or repo.get(private_key) is not False:
        raise ValueError('Unexpected repository visibility or ownership')
    owner = repo.get('owner')
    login = owner.get('login') if isinstance(owner, dict) else None
    if not isinstance(login, str) or login.casefold() != USERNAME.casefold():
        raise ValueError('Unexpected repository visibility or ownership')


def _history_query(batch):
    fragments = []
    for index, state in enumerate(batch):
        after = ', after: ' + json.dumps(state['cursor']) if state['cursor'] else ''
        history = '''history(first: 100, author: {id: $author}%s) {
            nodes { oid additions deletions author { user { id } } }
            pageInfo { hasNextPage endCursor }
        }''' % after
        target = '... on Commit { ' + history + ' }'
        if state['tip']:
            selection = 'object(oid: ' + json.dumps(state['tip']) + ') { __typename oid ' + target + ' }'
        else:
            selection = 'defaultBranchRef { target { __typename oid ' + target + ' } }'
        fragments.append(
            f'r{index}: repository(owner: "{USERNAME}", name: {json.dumps(state["name"])}, followRenames: false) '
            '{ isPrivate owner { login } ' + selection + ' }'
        )
    return 'query($author: ID!) { ' + '\n'.join(fragments) + ' }'


def collect_public_profile(token=None):
    """Return eleven allowlisted fields, or fail without returning partial totals."""
    if token is None:
        token = os.environ.get('GITHUB_TOKEN')
    calls = 0

    def request(path, body=None):
        nonlocal calls
        calls += 1
        if calls > MAX_REQUESTS:
            raise RuntimeError('Public statistics exceeded the per-run request budget')
        return _request_json(path, token, body)

    user = request(f'/users/{USERNAME}')
    if not isinstance(user, dict) or not isinstance(user.get('login'), str) or user['login'].casefold() != USERNAME.casefold():
        raise ValueError('Unexpected public user response')
    author_id = user.get('node_id')
    created = user.get('created_at')
    if not isinstance(author_id, str) or not author_id or not isinstance(created, str):
        raise ValueError('Incomplete public user metadata')
    followers = _counter(user.get('followers'))
    try:
        account_since = str(dt.date.fromisoformat(created[:10]).year).zfill(4)
    except ValueError:
        raise ValueError('Invalid public user creation date') from None

    repositories, names, stars = [], set(), 0
    page = 1
    while True:
        batch = request(f'/users/{USERNAME}/repos?type=owner&per_page=100&page={page}')
        if not isinstance(batch, list) or len(batch) > 100:
            raise ValueError('Invalid public repository page')
        for repo in batch:
            _owned_public(repo, 'private')
            name = repo.get('name')
            if not isinstance(name, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name) is None or name.casefold() in names:
                raise ValueError('Invalid or duplicated public repository name')
            if type(repo.get('fork')) is not bool:
                raise ValueError('Invalid public repository fork flag')
            count = _counter(repo.get('stargazers_count'))
            stars += 0 if repo['fork'] else count
            names.add(name.casefold())
            repositories.append({'name': name, 'tip': None, 'cursor': None,
                                 'cursors': set(), 'commits': set()})
        if len(batch) < 100:
            break
        page += 1

    unique_commits = {}
    pending = list(repositories)
    while pending:
        round_pending, pending = pending, []
        for offset in range(0, len(round_pending), BATCH_SIZE):
            batch = round_pending[offset:offset + BATCH_SIZE]
            response = request('/graphql', {
                'query': _history_query(batch), 'variables': {'author': author_id},
            })
            if not isinstance(response, dict) or response.get('errors') or not isinstance(response.get('data'), dict):
                raise RuntimeError('Public GitHub GraphQL statistics request failed')
            for index, state in enumerate(batch):
                repo = response['data'].get(f'r{index}')
                _owned_public(repo, 'isPrivate')
                if state['tip']:
                    target = repo.get('object')
                else:
                    branch = repo.get('defaultBranchRef')
                    if branch is None:
                        continue  # A legitimately empty repository has no branch.
                    if not isinstance(branch, dict):
                        raise ValueError('Invalid public default branch')
                    target = branch.get('target')
                if not isinstance(target, dict) or not isinstance(target.get('__typename'), str):
                    raise ValueError('Invalid public history target')
                if target['__typename'] != 'Commit':
                    if state['tip']:
                        raise ValueError('Public history target changed unexpectedly')
                    continue
                tip = target.get('oid')
                if not isinstance(tip, str) or OID.fullmatch(tip) is None:
                    raise ValueError('Invalid or changed public history tip')
                tip = tip.lower()
                if state['tip'] and tip != state['tip']:
                    raise ValueError('Invalid or changed public history tip')
                state['tip'] = tip
                history = target.get('history')
                if not isinstance(history, dict) or not isinstance(history.get('nodes'), list) or len(history['nodes']) > 100:
                    raise ValueError('Invalid public commit history page')
                for commit in history['nodes']:
                    if not isinstance(commit, dict):
                        raise ValueError('Invalid public commit metadata')
                    author = commit.get('author')
                    primary = author.get('user') if isinstance(author, dict) else None
                    if not isinstance(primary, dict) or primary.get('id') != author_id:
                        continue  # Do not count coauthor-only or unassociated IDs.
                    oid = commit.get('oid')
                    if not isinstance(oid, str) or OID.fullmatch(oid) is None:
                        raise ValueError('Invalid public commit identity')
                    oid = oid.lower()
                    totals = (_counter(commit.get('additions')), _counter(commit.get('deletions')))
                    if oid in unique_commits and unique_commits[oid] != totals:
                        raise ValueError('Conflicting public commit statistics')
                    unique_commits[oid] = totals
                    state['commits'].add(oid)
                pagination = history.get('pageInfo')
                if not isinstance(pagination, dict) or type(pagination.get('hasNextPage')) is not bool:
                    raise ValueError('Invalid public commit pagination')
                if pagination['hasNextPage']:
                    cursor = pagination.get('endCursor')
                    if not isinstance(cursor, str) or not cursor or cursor in state['cursors'] or not history['nodes']:
                        raise ValueError('Invalid or repeated public commit cursor')
                    state['cursors'].add(cursor)
                    state['cursor'] = cursor
                    pending.append(state)

    additions = sum(value[0] for value in unique_commits.values())
    deletions = sum(value[1] for value in unique_commits.values())
    return validate_snapshot({
        'username': USERNAME,
        'public_repositories': len(repositories),
        'public_original_repo_stars': stars,
        'followers': followers,
        'account_since': account_since,
        'updated_utc': dt.datetime.now(dt.timezone.utc).date().isoformat(),
        'authored_commits': len(unique_commits),
        'contributed_repositories': sum(bool(repo['commits']) for repo in repositories),
        'additions': additions, 'deletions': deletions, 'net_lines': additions - deletions,
    })

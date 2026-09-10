"""Read Git ancestry and annotate prompt history without trusting author dates.

Candidate for tools/git_ancestry.py. Reuses the existing offline, no-shell Git
command policy; no repository mutation, installation, or network operation.
"""
from __future__ import annotations

import heapq
from pathlib import Path
import subprocess

from tools.git_facts import GIT_TIMEOUT, SHA_RE, GitReadError, _command, _decode, _git_env, _run


def is_ancestor(repo: str, before: str, after: str, project_root: Path) -> bool | None:
    """True/False follows merge-base --is-ancestor; None means not verified.

    The comparison includes intermediate commits which are absent from CHG
    documents. Only hexadecimal SHA inputs are accepted, never refs or options.
    Missing objects/repositories/timeouts stay unknown; they are not False.
    """
    if not isinstance(repo, str) or not repo.strip():
        return None
    if any(not isinstance(sha, str) or SHA_RE.fullmatch(sha) is None for sha in (before, after)):
        return None
    try:
        project = Path(project_root).expanduser().resolve()
        configured = Path(repo).expanduser()
        directory = (configured if configured.is_absolute() else project / configured).resolve()
        if not directory.is_dir():
            return None
        root = Path(_decode(_run(directory, ['rev-parse', '--show-toplevel'])).strip()).resolve()
        resolved_before = _decode(_run(root, ['rev-parse', '--verify', before + '^{commit}'])).strip()
        resolved_after = _decode(_run(root, ['rev-parse', '--verify', after + '^{commit}'])).strip()
        result = subprocess.run(
            _command(root, ['merge-base', '--is-ancestor', resolved_before, resolved_after]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT,
            env=_git_env(),
            shell=False,
            check=False,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
    except (GitReadError, OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        pass
    return None


def annotate_history(history: list[dict], repo: str, project_root: Path, *, ancestor_check=None) -> dict:
    """Topologically order a small, already deduplicated same-repository history.

    Stable caller order breaks ties between unrelated commits. Author timestamps
    remain display metadata and never create ancestry edges or restoration facts.
    Each restoration needs both a verified ancestor and matching Git blob IDs.
    A per-call pair cache bounds repeated ancestor probes to two per commit pair.
    """
    rows = [dict(item, restores=[]) for item in history]
    check = ancestor_check or is_ancestor
    cache: dict[tuple[str, str], bool | None] = {}

    def relation(before, after):
        key = (before, after)
        if key not in cache:
            cache[key] = check(repo, before, after, project_root)
        return cache[key]

    edges = [set() for _ in rows]
    indegree = [0 for _ in rows]
    unknown_pairs = []
    inconsistent = []
    for i, before in enumerate(rows):
        for j in range(i + 1, len(rows)):
            after = rows[j]
            if before['sha'] == after['sha']:
                continue
            forward = relation(before['sha'], after['sha'])
            reverse = relation(after['sha'], before['sha'])
            if forward is None or reverse is None:
                unknown_pairs.append([before['sha'], after['sha']])
            if forward is True and reverse is True:
                inconsistent.append([before['sha'], after['sha']])
                continue
            if forward is True:
                edges[i].add(j)
                indegree[j] += 1
            elif reverse is True:
                edges[j].add(i)
                indegree[i] += 1

    ready = [index for index, count in enumerate(indegree) if not count]
    heapq.heapify(ready)
    order = []
    while ready:
        index = heapq.heappop(ready)
        order.append(index)
        for child in sorted(edges[index]):
            indegree[child] -= 1
            if not indegree[child]:
                heapq.heappush(ready, child)
    if len(order) != len(rows):
        # Impossible for verified unique Git commits. Preserve readable records
        # while refusing restoration claims from an inconsistent relation graph.
        inconsistent.append(['cycle'])
        order.extend(index for index in range(len(rows)) if index not in order)
    ordered = [rows[index] for index in order]

    if not inconsistent:
        for item in ordered:
            after_blobs = {file.get('after_blob') for file in item.get('files', []) if file.get('after_blob')}
            if not after_blobs:
                continue
            for earlier in ordered:
                if earlier['sha'] == item['sha']:
                    continue
                if relation(earlier['sha'], item['sha']) is not True:
                    continue
                before_blobs = {file.get('before_blob') for file in earlier.get('files', []) if file.get('before_blob')}
                if after_blobs & before_blobs:
                    item['restores'].append(earlier['sha'])

    return {
        'history': ordered,
        'ancestry': {
            'status': 'partial' if unknown_pairs or inconsistent else 'verified',
            'ordering': 'git-ancestry; caller order for unrelated commits',
            'checked_pairs': len(cache),
            'unverified_pairs': unknown_pairs,
            'inconsistent_pairs': inconsistent,
        },
    }

"""Read-only ancestry probes against isolated fictional Git test fixtures.

The test creates fixture commits only under this candidate's work/ directory.
When copied to the main repository's tests/, fixtures use its .work/ directory.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parent
sys.path.insert(0, str(SOURCE_ROOT))
CANDIDATE = HERE / 'git_ancestry.py'
if CANDIDATE.is_file():
    spec = importlib.util.spec_from_file_location('candidate_git_ancestry', CANDIDATE)
    ancestry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ancestry)
else:
    from tools import git_ancestry as ancestry


class GitAncestryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = HERE / 'work' if CANDIDATE.is_file() else HERE.parent / '.work'
        work.mkdir(exist_ok=True)
        cls.fixture = Path(tempfile.mkdtemp(prefix='ancestry-fixture-', dir=work)).resolve()
        assert cls.fixture.is_relative_to(work.resolve())
        cls.repo = cls.fixture / 'repo'
        cls.repo.mkdir()
        cls.docs = cls.fixture / 'project-documents'
        cls.docs.mkdir()
        cls.git('init', '--initial-branch=main')
        cls.git('config', 'user.name', 'Fictional Ancestry Test')
        cls.git('config', 'user.email', 'ancestry-test@example.invalid')
        cls.git('config', 'commit.gpgsign', 'false')
        cls.git('config', 'core.autocrlf', 'false')
        cls.git('config', 'core.hooksPath', str(cls.fixture / 'no-hooks'))
        cls.base = cls.change('A\n', '2026-09-05T08:00:00+00:00', 'fictional initial')
        cls.modified = cls.change('B\n', '2030-01-01T00:00:00+00:00', 'fictional modified with future author date')
        (cls.repo / 'unrelated.txt').write_text('intermediate\n', encoding='utf-8')
        cls.git('add', '--', 'unrelated.txt')
        cls.git('commit', '-m', 'fictional unreferenced intermediate')
        cls.intermediate = cls.git('rev-parse', 'HEAD').strip()
        cls.restored = cls.change('A\n', '2020-01-01T00:00:00+00:00', 'fictional restored with old author date')
        cls.git('switch', '-c', 'fictional-divergent', cls.base)
        cls.divergent_modified = cls.change('C\n', '2027-01-01T00:00:00+00:00', 'fictional divergent modification')
        cls.divergent_restored = cls.change('A\n', '2028-01-01T00:00:00+00:00', 'fictional divergent equal content')
        cls.git('switch', 'main')
        receipt = {'fictional': True, 'repo': str(cls.repo), 'base': cls.base, 'modified': cls.modified,
                   'intermediate': cls.intermediate, 'restored': cls.restored,
                   'divergent_modified': cls.divergent_modified, 'divergent_restored': cls.divergent_restored,
                   'note': 'Test commit author dates deliberately differ from actual creation time.'}
        (cls.fixture / 'fixture-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')

    @classmethod
    def git(cls, *args, env=None):
        result = subprocess.run(['git', '-C', str(cls.repo), *args], capture_output=True,
                                check=True, timeout=20, shell=False, env=env)
        return result.stdout.decode('utf-8')

    @classmethod
    def change(cls, content, date, subject):
        (cls.repo / 'prompt.md').write_text(content, encoding='utf-8', newline='\n')
        cls.git('add', '--', 'prompt.md')
        env = os.environ.copy()
        env['GIT_AUTHOR_DATE'] = date
        # Committer date is real; only author dates model rebased/imported history.
        env.pop('GIT_COMMITTER_DATE', None)
        cls.git('commit', '-m', subject, env=env)
        return cls.git('rev-parse', 'HEAD').strip()

    @classmethod
    def row(cls, sha):
        parent_line = cls.git('show', '-s', '--format=%P', sha).strip()
        before = cls.git('rev-parse', parent_line.split()[0] + ':prompt.md').strip() if parent_line else None
        return {'sha': sha, 'date': cls.git('show', '-s', '--format=%aI', sha).strip(),
                'files': [{'path': 'prompt.md', 'before_blob': before,
                           'after_blob': cls.git('rev-parse', sha + ':prompt.md').strip()}]}

    def annotate(self, shas, **kwargs):
        return ancestry.annotate_history([self.row(sha) for sha in shas], str(self.repo), self.docs, **kwargs)

    def test_backdated_author_dates_follow_git_ancestry(self):
        result = self.annotate([self.restored, self.base, self.modified])
        self.assertEqual([row['sha'] for row in result['history']], [self.base, self.modified, self.restored])
        self.assertEqual(result['history'][-1]['restores'], [self.modified])
        self.assertEqual(result['history'][1]['restores'], [])
        self.assertEqual(result['ancestry']['status'], 'verified')

    def test_divergent_branch_same_blob_is_not_restoration(self):
        self.assertFalse(ancestry.is_ancestor(str(self.repo), self.modified, self.divergent_restored, self.docs))
        result = self.annotate([self.modified, self.divergent_restored])
        self.assertTrue(all(not row['restores'] for row in result['history']))

    def test_omitted_intermediate_commit_still_proves_ancestry(self):
        self.assertNotEqual(self.git('rev-parse', self.restored + '^').strip(), self.modified)
        result = self.annotate([self.restored, self.modified])
        self.assertEqual([row['sha'] for row in result['history']], [self.modified, self.restored])
        self.assertEqual(result['history'][-1]['restores'], [self.modified])

    def test_relative_repo_with_separate_docs(self):
        self.assertTrue(ancestry.is_ancestor('../repo', self.modified, self.restored, self.docs))
        self.assertFalse(ancestry.is_ancestor('../repo', self.restored, self.modified, self.docs))

    def test_invalid_sha_and_missing_objects_are_unknown(self):
        for value in ['HEAD', '--help', 'a' * 6, 'f' * 41, 'f' * 40]:
            self.assertIsNone(ancestry.is_ancestor(str(self.repo), value, self.restored, self.docs))
        self.assertIsNone(ancestry.is_ancestor(str(self.fixture / 'absent'), self.modified, self.restored, self.docs))

    def test_unknown_relation_has_no_restoration_claim(self):
        result = self.annotate([self.modified, self.restored], ancestor_check=lambda *args: None)
        self.assertEqual(result['ancestry']['status'], 'partial')
        self.assertEqual(len(result['ancestry']['unverified_pairs']), 1)
        self.assertTrue(all(not row['restores'] for row in result['history']))

    def test_relation_pairs_are_cached(self):
        counts = {}
        def check(repo, before, after, project_root):
            counts[(before, after)] = counts.get((before, after), 0) + 1
            return ancestry.is_ancestor(repo, before, after, project_root)
        self.annotate([self.restored, self.base, self.modified], ancestor_check=check)
        self.assertEqual(len(counts), 6)
        self.assertEqual(set(counts.values()), {1})

    def test_empty_history_requires_no_git_access(self):
        result = ancestry.annotate_history([], 'missing', self.docs, ancestor_check=lambda *args: self.fail('Unexpected Git probe'))
        self.assertEqual(result['history'], [])
        self.assertEqual(result['ancestry']['status'], 'verified')


if __name__ == '__main__':
    unittest.main(verbosity=2)

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import yaml
import build


class ProfilesAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='test-profiles-', dir=build.ROOT / '.work')
        self.root = Path(self.temp.name)
        shutil.copytree(build.ROOT / 'src', self.root / 'src')
        for name in ['paperboat-agent', 'rain-window-film']:
            shutil.copytree(build.ROOT / 'projects' / name, self.root / 'projects' / name)
        # Use an actual, reachable fixture while keeping the test's files isolated.
        for path in [*(self.root / 'projects/paperboat-agent/changes').glob('*.md'), self.root / 'projects/paperboat-agent/profile.yaml']:
            path.write_text(path.read_text(encoding='utf-8').replace('../../.work/agent-demo-history', (build.ROOT / '.work/agent-demo-history').as_posix()), encoding='utf-8')

    def tearDown(self):
        build.checked_child(self.root, build.ROOT / '.work')
        self.temp.cleanup()

    def bundle(self):
        raw = (self.root / 'site/assets/project-data.js').read_text(encoding='utf-8')
        return json.loads(raw.split('window.DEVPLM_DATA = ', 1)[1].strip().removesuffix(';'))

    def test_types_share_documents_but_not_software_master_data(self):
        build.build(self.root)
        projects = self.bundle()['projects']
        self.assertEqual({p['type'] for p in projects}, {'agent', 'aigc'})
        for p in projects:
            self.assertTrue(p['example'])
            self.assertIsNone(p['onboarding'])
            self.assertEqual(p['apis'], [])
            self.assertEqual(p['screens'], [])
            for group in ['requirements', 'changes', 'tests', 'releases', 'incidents', 'audits', 'reviews']:
                self.assertTrue(p[group], group)

    def test_prompt_history_is_from_git_and_detects_exact_restoration(self):
        build.build(self.root)
        agent = next(p for p in self.bundle()['projects'] if p['type'] == 'agent')
        voice = next(o for o in agent['profileObjects'] if o['id'] == 'SEG-PAPER-VOICE')
        facts = next(o for o in agent['profileObjects'] if o['id'] == 'SEG-PAPER-FACTS')
        self.assertTrue(any(h['restores'] for h in voice['history']))
        self.assertEqual(len(voice['history']), 3)
        self.assertEqual(len(facts['history']), 2)
        for obj in [voice, facts]:
            for h in obj['history']:
                self.assertTrue(all(f['path'] == obj['git_path'] for f in h['files']))
                self.assertTrue(all(len(h['sha']) == 40 for h in obj['history']))

    def test_unreachable_repo_degrades_but_build_continues(self):
        for path in (self.root / 'projects/paperboat-agent/changes').glob('*.md'):
            doc = build.Document(path, self.root)
            text = path.read_text(encoding='utf-8').replace(doc.data['repo'], (self.root / 'not-there').as_posix())
            path.write_text(text, encoding='utf-8')
        self.assertTrue(build.build(self.root)['ok'])
        agent = next(p for p in self.bundle()['projects'] if p['type'] == 'agent')
        self.assertTrue(all(c['git']['status'] == 'unavailable' for c in agent['changes']))
        self.assertTrue(all(c['git']['reason'] for c in agent['changes']))

    def test_broken_profile_reference_and_stable_id_report_location(self):
        path = self.root / 'projects/paperboat-agent/prompts/SEG-PAPER-VOICE.md'
        path.write_text(path.read_text(encoding='utf-8').replace('SEG-PAPER-VOICE', 'WRONG-SEGMENT', 1), encoding='utf-8')
        with self.assertRaises(build.BuildError) as error:
            build.build(self.root)
        self.assertRegex(str(error.exception), r'prompts/SEG-PAPER-VOICE.md:\d+:')
        self.assertIn('稳定 id', str(error.exception))

    def test_change_cannot_reference_unknown_requirement(self):
        path = self.root / 'projects/paperboat-agent/changes/CHG-PAPER-002.md'
        path.write_text(path.read_text(encoding='utf-8').replace('REQ-PAPER-002', 'MISSING-REQ'), encoding='utf-8')
        with self.assertRaises(build.BuildError) as error:
            build.build(self.root)
        self.assertRegex(str(error.exception), r'changes/CHG-PAPER-002.md:\d+:')

    def test_duplicate_change_does_not_inflate_prompt_history(self):
        source = self.root / 'projects/paperboat-agent/changes/CHG-PAPER-002.md'
        target = source.with_name('CHG-PAPER-004.md')
        target.write_text(source.read_text(encoding='utf-8').replace('CHG-PAPER-002', 'CHG-PAPER-004'), encoding='utf-8')
        build.build(self.root)
        agent = next(p for p in self.bundle()['projects'] if p['type'] == 'agent')
        facts = next(o for o in agent['profileObjects'] if o['id'] == 'SEG-PAPER-FACTS')
        self.assertEqual(len(facts['history']), 2)
        self.assertTrue(any(len(h['changes']) == 2 for h in facts['history']))

    def test_software_environment_target_rejected_for_agent(self):
        path = next((self.root / 'projects/paperboat-agent/records').glob('*.md'))
        doc = build.Document(path, self.root)
        path.write_text(path.read_text(encoding='utf-8').replace(doc.data['target'], '#operations'), encoding='utf-8')
        with self.assertRaises(build.BuildError) as error:
            build.build(self.root)
        self.assertIn('此项目类型', str(error.exception))

    def test_real_project_exception_is_scoped_to_dev_plm(self):
        path = self.root / 'projects/paperboat-agent/project.yaml'
        obj = yaml.safe_load(path.read_text(encoding='utf-8'))
        obj['example'] = False
        path.write_text(yaml.safe_dump(obj), encoding='utf-8')
        with self.assertRaises(build.BuildError) as error:
            build.build(self.root)
        self.assertIn('仅 dev-plm', str(error.exception))


if __name__ == '__main__':
    unittest.main()

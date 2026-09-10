import copy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

import yaml

import build


class BuildAcceptance(unittest.TestCase):
    def setUp(self):
        work = build.ROOT / '.work'
        work.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='test-build-', dir=work)
        self.root = Path(self.temp.name)
        # Keep the original two-project regression fixture independent of later additions.
        shutil.copytree(build.ROOT / 'src', self.root / 'src')
        for name in ['qingdan', 'event-inbox']:
            shutil.copytree(build.ROOT / 'projects' / name, self.root / 'projects' / name)

    def tearDown(self):
        # This temporary root is created within .work and owns every child.
        build.checked_child(self.root, build.ROOT / '.work')
        self.temp.cleanup()

    def bundle(self):
        text = (self.root / 'site/assets/project-data.js').read_text(encoding='utf-8')
        return json.loads(text.split('window.DEVPLM_DATA = ', 1)[1].rstrip().removesuffix(';'))

    def test_offline_build_and_generated_markers(self):
        with patch.object(socket, 'create_connection', side_effect=AssertionError('Network is not permitted')):
            report = build.build(self.root)
        self.assertEqual(report['projects'], 2)
        self.assertEqual(report['operations'], 7)
        for asset in (self.root / 'site').rglob('*'):
            if asset.suffix in ['.html', '.js', '.css']:
                self.assertIn(build.GENERATED, asset.read_text(encoding='utf-8').splitlines()[0])
        self.assertIn('linguist-generated=true', (self.root / 'site/assets/.gitattributes').read_text())
        self.assertFalse(list((self.root / 'site').rglob('demo-data.js')))
        self.assertFalse(list((self.root / 'site').rglob('demo-files.js')))

    def test_edit_source_then_rebuild_changes_view(self):
        build.build(self.root)
        old = self.bundle()
        source = self.root / 'projects/qingdan/project.yaml'
        data = yaml.safe_load(source.read_text(encoding='utf-8'))
        data['name'] = '源文件改名验证（示例）'
        source.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
        build.build(self.root)
        new = self.bundle()
        self.assertNotEqual(old['build']['sourceSha256'], new['build']['sourceSha256'])
        self.assertEqual(next(p for p in new['projects'] if p['id'] == 'qingdan')['name'], data['name'])
        self.assertEqual((self.root / 'src/index.html').read_text(encoding='utf-8'), (build.ROOT / 'src/index.html').read_text(encoding='utf-8'))

    def test_third_project_needs_no_template_edits(self):
        source = self.root / 'projects/event-inbox'
        target = self.root / 'projects/another-service'
        shutil.copytree(source, target)
        meta = yaml.safe_load((target / 'project.yaml').read_text(encoding='utf-8'))
        meta.update(id='another-service', name='第三个项目（示例）')
        (target / 'project.yaml').write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding='utf-8')
        result = build.build(self.root)
        self.assertEqual(result['projects'], 3)
        self.assertTrue(any(p['id'] == 'another-service' for p in self.bundle()['projects']))

    def test_broken_requirement_reports_line_and_keeps_last_site(self):
        build.build(self.root)
        output = self.root / 'site/assets/project-data.js'
        before = hashlib.sha256(output.read_bytes()).hexdigest()
        source = self.root / 'projects/qingdan/api/openapi.json'
        text = source.read_text(encoding='utf-8').replace('DEMO-REQ-001', 'MISSING-REQ-999', 1)
        source.write_text(text, encoding='utf-8')
        line = next(i + 1 for i, value in enumerate(text.splitlines()) if 'MISSING-REQ-999' in value)
        with self.assertRaises(build.BuildError) as caught:
            build.build(self.root)
        self.assertIn(f'projects/qingdan/api/openapi.json:{line}:', str(caught.exception))
        self.assertIn('MISSING-REQ-999', str(caught.exception))
        self.assertEqual(before, hashlib.sha256(output.read_bytes()).hexdigest())

    def test_broken_test_record_reports_source_line(self):
        source = next((self.root / 'projects/qingdan/tests').glob('*.md'))
        text = source.read_text(encoding='utf-8')
        data = build.Document(source, self.root).data
        text = text.replace(data['record'], 'MISSING-LOG-999')
        source.write_text(text, encoding='utf-8')
        line = next(i + 1 for i, value in enumerate(text.splitlines()) if 'MISSING-LOG-999' in value)
        with self.assertRaises(build.BuildError) as caught:
            build.build(self.root)
        self.assertIn(f'{source.relative_to(self.root).as_posix()}:{line}:', str(caught.exception))

    def test_official_schema_rejects_invalid_nested_schema_object(self):
        source = self.root / 'projects/qingdan/api/openapi.json'
        data = json.loads(source.read_text(encoding='utf-8'))
        data['components']['schemas']['Task']['properties']['title']['type'] = 'not-a-json-schema-type'
        source.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        with self.assertRaises(build.BuildError) as caught:
            build.build(self.root)
        self.assertIn('OpenAPI:', str(caught.exception))
        self.assertIn('projects/qingdan/api/openapi.json:', str(caught.exception))

    def test_schema_reference_must_exist(self):
        source = self.root / 'projects/qingdan/api/openapi.json'
        text = source.read_text(encoding='utf-8').replace('#/components/schemas/Task', '#/components/schemas/AbsentTask', 1)
        source.write_text(text, encoding='utf-8')
        with self.assertRaises(build.BuildError) as caught:
            build.build(self.root)
        self.assertIn('AbsentTask', str(caught.exception))

    def test_api_examples_are_direct_contract_values(self):
        build.build(self.root)
        for p in self.bundle()['projects']:
            spec = json.loads((self.root / 'projects' / p['id'] / 'api/openapi.json').read_text(encoding='utf-8'))
            for a in p['apis']:
                operation = spec['paths'][a['path']][a['method'].lower()]
                for media in a['requestExamples']:
                    originals = operation['requestBody']['content'][media['mime']]['examples']
                    for example in media['examples']:
                        self.assertEqual(example['value'], originals[example['name']]['value'])
                for response in a['responses']:
                    original_response = operation['responses'][response['code']]
                    for media in response['samples']:
                        originals = original_response['content'][media['mime']]['examples']
                        for example in media['examples']:
                            self.assertEqual(example['value'], originals[example['name']]['value'])

    def test_file_view_and_environment_have_one_source(self):
        build.build(self.root)
        for p in self.bundle()['projects']:
            for f in p['files']:
                self.assertEqual(f['content'], (self.root / 'projects' / p['id'] / f['path']).read_text(encoding='utf-8'))
            urls = {s['x-environment']: s['url'] for s in p['servers']}
            for env in p['onboarding']['environments']:
                self.assertEqual(env['url'], urls[env['server_ref']])
            on_disk = yaml.safe_load((self.root / 'projects' / p['id'] / 'onboarding.yaml').read_text(encoding='utf-8'))
            self.assertTrue(all('url' not in env and 'base_url' not in env for env in on_disk['environments']))
        service = next(p for p in self.bundle()['projects'] if p['kind'] == 'service')
        self.assertFalse(service['onboarding']['frontend']['applicable'])
        self.assertEqual(service['screens'], [])

    def test_duplicate_yaml_keys_fail_with_source_location(self):
        source = self.root / 'projects/qingdan/project.yaml'
        source.write_text(source.read_text(encoding='utf-8') + '\nname: duplicate\n', encoding='utf-8')
        with self.assertRaises(build.BuildError) as caught:
            build.build(self.root)
        self.assertIn('projects/qingdan/project.yaml:', str(caught.exception))

    def test_original_markdown_roundtrip(self):
        original = '\n第一段\n## 补充条件\n第二段\n## 当前理解\n这仍是用户原话\n> 保留引用\n'
        quoted = '\n'.join('> ' + line for line in original.split('\n'))
        body = '## 用户原话\n\n' + quoted + '\n\n## 当前理解\n\n另外记录的理解。\n'
        self.assertEqual(build.section(body, '用户原话'), original)
        self.assertEqual(build.section(body, '当前理解'), '另外记录的理解。')

    def test_file_target_must_exist(self):
        source = next((self.root / 'projects/qingdan/records').glob('*.md'))
        doc = build.Document(source, self.root)
        text = source.read_text(encoding='utf-8').replace(doc.data['target'], '#files/DOES-NOT-EXIST.md')
        source.write_text(text, encoding='utf-8')
        with self.assertRaises(build.BuildError) as caught:
            build.build(self.root)
        self.assertIn('DOES-NOT-EXIST.md', str(caught.exception))
        self.assertIn(source.relative_to(self.root).as_posix()+':', str(caught.exception))

    def test_parameter_reference_and_operation_override(self):
        source = self.root / 'projects/qingdan/api/openapi.json'
        spec = json.loads(source.read_text(encoding='utf-8'))
        op = spec['paths']['/v1/tasks']['post']
        param = next(p for p in op['parameters'] if p['name'] == 'Idempotency-Key')
        spec['components'].setdefault('parameters', {})['TaskIdempotencyKey'] = copy.deepcopy(param)
        spec['paths']['/v1/tasks']['parameters'] = [{'$ref': '#/components/parameters/TaskIdempotencyKey'}]
        op['parameters'] = [{'$ref': '#/components/parameters/TaskIdempotencyKey'}]
        source.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
        build.build(self.root)
        project = next(p for p in self.bundle()['projects'] if p['id'] == 'qingdan')
        projected = next(a for a in project['apis'] if a['id'] == 'createTask')['parameters']
        self.assertEqual(len([p for p in projected if p['name'] == 'Idempotency-Key']), 1)
        self.assertTrue(next(p for p in projected if p['name'] == 'Idempotency-Key')['required'])


if __name__ == '__main__':
    unittest.main()

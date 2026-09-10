import unittest
import build


class SelfProjectAcceptance(unittest.TestCase):
    def test_real_self_project_originals_design_and_code_entries(self):
        p, docs = build.load_project(build.ROOT / 'projects/dev-plm', build.ROOT)
        expected = [
            '项目档案按前后端分开，各自交代技术栈',
            '日志要变成类似 ERP / CRM / PLM 的系统，一切可观察、可回溯、可溯源',
            '要能记录「我每次提出的需求、我每次做的改动」——需求必须成为一等公民',
            '前后端对接文档要有明确的存放位置',
            '人类开发者要能参与，不能只有 AI 维护得动',
            '要按项目区分',
            '要有入口能直接看前端代码和后端代码',
            '页面不能是文件的副本，必须单一数据源',
            '要能同时装下软件工程、Agent 工程和 AIGC 项目',
            '每次写下新提示词，Agent 对我的项目做了哪些调整、具体在哪个环节变了，要能看见',
            '这个系统是奔着团队协作去的',
            '设计数据库表结构，确定前后端技术栈',
        ]
        self.assertFalse(p['example'])
        self.assertEqual(p['type'], 'software')
        self.assertEqual([r['original'] for r in p['requirements'][:12]], expected)
        self.assertEqual(p['changes'][0]['git']['status'], 'no_history')
        commit = p['changes'][1]['commit']
        self.assertEqual([commit] if isinstance(commit, str) else commit, ['d126b25ef7e4813801d8dfada7ec6213e766b4c4'])
        self.assertTrue(p['onboarding']['frontend']['applicable'])
        self.assertTrue(p['onboarding']['backend']['applicable'])
        self.assertIn('FastAPI', p['onboarding']['backend']['framework'])
        self.assertEqual(set(p['designFiles']), {'design/stack.md', 'design/database.md'})
        for f in p['codeFiles']:
            self.assertEqual(f['content'], (build.ROOT / f['path']).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

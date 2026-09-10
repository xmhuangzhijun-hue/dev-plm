"""Independent tests; fixtures live only inside this candidate directory."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("git_facts", HERE / "tools/git_facts.py")
git_facts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(git_facts)


class GitFactsTests(unittest.TestCase):
    def test_unicode_separators_inside_git_line_preserve_text_and_line_number(self):
        text = 'alpha\u2028+beta\u2029gamma\vdelta'
        hunks = git_facts._parse_hunks('@@ -0,0 +1 @@\n+' + text + '\n')
        self.assertEqual(len(hunks[0]['lines']), 1)
        self.assertEqual(hunks[0]['lines'][0]['new_line'], 1)
        self.assertEqual(hunks[0]['lines'][0]['text'], text)

    @classmethod
    def setUpClass(cls):
        cls.work = HERE / ".work"
        cls.work.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="fixture-", dir=cls.work)
        cls.root = Path(cls.temp.name).resolve()
        cls.repo = cls.root / "repo with spaces"
        cls.repo.mkdir()
        cls.git("init", "--initial-branch=main")
        cls.git("config", "user.name", "Test Fixture")
        cls.git("config", "user.email", "fixture@example.invalid")
        cls.git("config", "commit.gpgsign", "false")
        cls.git("config", "core.autocrlf", "false")
        cls.git("config", "core.hooksPath", str(cls.root / "no-hooks"))
        (cls.repo / "prompt.md").write_text("one\n", encoding="utf-8")
        (cls.repo / "app.py").write_text("print(1)\n", encoding="utf-8")
        (cls.repo / "image.bin").write_bytes(b"\x00\x01\x02")
        cls.initial = cls.commit("Initial files")
        (cls.repo / "prompt.md").write_text("two\n", encoding="utf-8")
        (cls.repo / "app.py").write_text("print(1)\nprint(2)\n", encoding="utf-8")
        cls.modified = cls.commit("Deliberately not a semantic description")
        cls.git("mv", "prompt.md", "提示词 renamed.md")
        cls.renamed = cls.commit("Rename prompt")
        (cls.repo / "-unrelated.txt").write_text("unrelated\n", encoding="utf-8")
        cls.unrelated = cls.commit("Unrelated file")
        (cls.repo / "提示词 renamed.md").write_text("one\n", encoding="utf-8")
        cls.restored = cls.commit("Subject does not say restore")
        (cls.repo / "large.txt").write_text("".join(f"line {i:05d} with data\n" for i in range(12000)), encoding="utf-8")
        cls.large = cls.commit("Large patch")
        cls.git("rm", "app.py")
        cls.deleted = cls.commit("Remove a file")
        cls.git("commit", "--allow-empty", "-m", "Empty commit")
        cls.empty = cls.git("rev-parse", "HEAD").strip()

    @classmethod
    def tearDownClass(cls):
        # tempfile's resolved fixture path is a child of the candidate root.
        cls.root.relative_to(cls.work.resolve())
        cls.temp.cleanup()

    @classmethod
    def git(cls, *args):
        result = subprocess.run(["git", "-C", str(cls.repo), *args], capture_output=True,
                                check=True, timeout=20, shell=False, env=git_facts._git_env())
        return result.stdout.decode("utf-8")

    @classmethod
    def commit(cls, subject):
        cls.git("add", "--", ".")
        cls.git("commit", "-m", subject)
        return cls.git("rev-parse", "HEAD").strip()

    def extract(self, commits, paths=None):
        return git_facts.extract_change(str(self.repo), commits, self.repo, paths)

    def test_root_commit_and_true_line_numbers(self):
        result = self.extract([self.initial])
        self.assertEqual(result["status"], "available")
        commit = result["commits"][0]
        self.assertEqual(commit["parents"], [])
        file = next(f for f in commit["files"] if f["path"] == "prompt.md")
        self.assertIsNone(file["before_blob"])
        self.assertEqual(file["after_blob"], self.git("rev-parse", self.initial + ":prompt.md").strip())
        line = file["hunks"][0]["lines"][0]
        self.assertEqual((line["kind"], line["old_line"], line["new_line"]), ("addition", None, 1))
        self.assertIn("+one", file["patch"])

    def test_modified_file_and_blob_restore_evidence(self):
        before = self.extract([self.modified], ["prompt.md"])["commits"][0]["files"][0]
        restored = self.extract([self.restored], ["提示词 renamed.md"])["commits"][0]["files"][0]
        self.assertEqual(before["before_blob"], restored["after_blob"])
        self.assertEqual((before["additions"], before["deletions"]), (1, 1))
        self.assertEqual([line["kind"] for line in before["hunks"][0]["lines"]], ["deletion", "addition"])

    def test_rename_and_old_path_filter(self):
        result = self.extract([self.renamed], ["prompt.md"])
        file = result["commits"][0]["files"][0]
        self.assertTrue(file["status"].startswith("R"))
        self.assertEqual(file["old_path"], "prompt.md")
        self.assertEqual(file["path"], "提示词 renamed.md")
        self.assertEqual(file["before_blob"], file["after_blob"])
        self.assertIn("rename from", file["patch"])

    def test_paths_include_only_commits_that_changed_requested_file(self):
        result = self.extract([self.modified, self.renamed, self.unrelated], ["prompt.md"])
        self.assertEqual([c["sha"] for c in result["commits"]], [self.modified, self.renamed])
        self.assertEqual(result["status"], "available")
        absolute = self.extract([self.modified], [str(self.repo / "prompt.md")])
        self.assertEqual(absolute["commits"][0]["totals"]["files"], 1)

    def test_literal_dash_path_and_directory_filter(self):
        result = self.extract([self.unrelated], ["-unrelated.txt"])
        self.assertEqual(result["commits"][0]["files"][0]["path"], "-unrelated.txt")
        self.assertEqual(self.extract([self.initial], ["."])["commits"][0]["totals"]["files"], 3)

    def test_binary_is_reported_without_fabricated_line_counts(self):
        file = self.extract([self.initial], ["image.bin"])["commits"][0]["files"][0]
        self.assertTrue(file["binary"])
        self.assertIsNone(file["additions"])
        self.assertIsNone(file["deletions"])
        self.assertIn("Binary files", file["patch"])

    def test_large_patch_explicitly_truncates_but_keeps_full_counts(self):
        result = self.extract([self.large])
        file = result["commits"][0]["files"][0]
        self.assertEqual(result["status"], "partial")
        self.assertTrue(file["truncated"])
        self.assertGreater(file["bytes_original"], git_facts.PATCH_LIMIT)
        self.assertLessEqual(file["bytes_kept"], git_facts.PATCH_LIMIT)
        self.assertEqual(file["additions"], 12000)
        self.assertEqual(file["hunk_count"], 1)
        self.assertTrue(file["patch"].endswith("\n"))

    def test_deleted_file_blobs(self):
        file = self.extract([self.deleted])["commits"][0]["files"][0]
        self.assertEqual(file["status"], "D")
        self.assertIsNone(file["after_blob"])
        self.assertIsNotNone(file["before_blob"])

    def test_no_history_and_empty_commit(self):
        self.assertEqual(self.extract([])["status"], "no_history")
        self.assertEqual(self.extract([self.unrelated], ["prompt.md"])["status"], "no_history")
        self.assertEqual(self.extract([self.initial], [])["status"], "no_history")
        empty = self.extract([self.empty])
        self.assertEqual(empty["status"], "available")
        self.assertEqual(empty["commits"][0]["totals"]["files"], 0)

    def test_invalid_sha_and_unreachable_repo_degrade(self):
        result = self.extract([self.initial[:8], "HEAD", "--help", "f" * 40])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["commits"]), 1)
        self.assertEqual(len(result["skipped"]), 3)
        self.assertEqual(self.extract(["notasha"])["status"], "unavailable")
        absent = git_facts.extract_change(str(self.root / "absent"), [self.initial], self.root)
        self.assertEqual(absent["status"], "unavailable")
        non_git = git_facts.extract_change(str(self.root), [self.initial], self.root)
        self.assertEqual(non_git["status"], "unavailable")
        self.assertEqual(git_facts.extract_change("", [self.initial], self.repo)["status"], "unavailable")

    def test_outside_project_paths_rejected(self):
        self.assertEqual(self.extract([self.initial], ["../elsewhere"])["status"], "unavailable")

    def test_relative_repo_outside_documentation_directory(self):
        project_docs = self.root / "project documentation"
        project_docs.mkdir(exist_ok=True)
        result = git_facts.extract_change("../repo with spaces", [self.modified], project_docs, ["prompt.md"])
        self.assertEqual(result["status"], "available")
        self.assertEqual([file["path"] for file in result["commits"][0]["files"]], ["prompt.md"])

    def test_absolute_unrelated_repo_with_separate_documentation(self):
        project_docs = self.root / "another documentation directory"
        project_docs.mkdir(exist_ok=True)
        result = git_facts.extract_change(str(self.repo), [self.modified], project_docs, ["prompt.md"])
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["commits"][0]["sha"], self.modified)
        self.assertEqual([file["path"] for file in result["commits"][0]["files"]], ["prompt.md"])
        escaped = git_facts.extract_change(str(self.repo), [self.modified], project_docs, [str(project_docs / "prompt.md")])
        self.assertEqual(escaped["status"], "unavailable")

    def test_duplicate_commits_and_deterministic_summary(self):
        result = self.extract([self.modified, self.modified[:8]])
        self.assertEqual(len(result["commits"]), 1)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["summary"], self.extract([self.modified])["summary"])
        self.assertNotIn("Deliberately", result["summary"])
        self.assertIn("文件分类不表示改动意图", result["summary"])

    def test_filename_parser_handles_tabs_newlines_and_rename(self):
        stats = git_facts._parse_numstat(b"3\t2\tstrange\tname\n.txt\0" + b"0\t0\t\0old\n.md\0new\t.md\0")
        self.assertEqual(stats[(None, "strange\tname\n.txt")]["additions"], 3)
        self.assertIn(("old\n.md", "new\t.md"), stats)
        raw = b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" R100\0old\n.md\0new\t.md\0"
        self.assertEqual(git_facts._parse_raw(raw)[0]["path"], "new\t.md")

    def test_gitlink_oid_is_not_mislabeled_as_a_blob(self):
        raw = b":160000 160000 " + b"1" * 40 + b" " + b"2" * 40 + b" M\0submodule\0"
        file = git_facts._parse_raw(raw)[0]
        self.assertIsNone(file["before_blob"])
        self.assertEqual(file["before_object"], "1" * 40)
        self.assertEqual(file["before_mode"], "160000")

    def test_external_diff_is_disabled(self):
        self.git("config", "diff.external", "nonexistent-external-diff-for-test")
        try:
            self.assertEqual(self.extract([self.modified])["status"], "available")
        finally:
            self.git("config", "--unset", "diff.external")

    def test_timeout_degrades_patch_without_dropping_file(self):
        with patch.object(git_facts, "_patch", side_effect=git_facts.GitReadError("test timeout")):
            result = self.extract([self.modified], ["prompt.md"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["commits"][0]["totals"]["files"], 1)
        self.assertIsNone(result["commits"][0]["totals"]["hunks"])
        self.assertFalse(result["commits"][0]["files"][0]["patch_available"])

    def test_first_parent_merge(self):
        first_parent = self.empty
        self.git("switch", "-c", "test-merge-side", self.initial)
        (self.repo / "side.txt").write_text("side\n", encoding="utf-8")
        second_parent = self.commit("Side commit")
        self.git("switch", "main")
        self.git("merge", "--no-ff", "test-merge-side", "-m", "Merge fixture")
        merge = self.git("rev-parse", "HEAD").strip()
        result = self.extract([merge])
        commit = result["commits"][0]
        self.assertEqual(commit["parents"], [first_parent, second_parent])
        self.assertEqual(commit["comparison"], "first-parent")
        self.assertEqual([f["path"] for f in commit["files"]], ["side.txt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

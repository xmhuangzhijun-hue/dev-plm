"""Read deterministic Git facts for a bounded list of commits.

No shell, network, install, repository mutation, or semantic change narration.
Only the first parent is compared for merge commits. A relative repo is resolved
from project_root (the project documentation directory). Filter paths and returned
file paths are relative to the independent target Git worktree root.
"""
from __future__ import annotations

from collections import Counter
import codecs
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import threading

PATCH_LIMIT = 48 * 1024
GIT_TIMEOUT = 20
SHA_RE = re.compile(r"[0-9a-fA-F]{7,40}\Z")
HUNK_RE = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
CATEGORIES = {
    ".md": "Markdown 文件", ".markdown": "Markdown 文件",
    ".py": "Python 文件", ".js": "JavaScript 文件", ".mjs": "JavaScript 文件",
    ".ts": "TypeScript 文件", ".tsx": "TSX 文件", ".jsx": "JSX 文件",
    ".html": "HTML 文件", ".css": "CSS 文件", ".json": "JSON 文件",
    ".yaml": "YAML 文件", ".yml": "YAML 文件", ".sql": "SQL 文件",
    ".txt": "文本文件", ".svg": "SVG 文件", ".png": "PNG 文件",
    ".jpg": "JPEG 文件", ".jpeg": "JPEG 文件", ".webp": "WebP 文件",
}


class GitReadError(Exception):
    pass


def _decode(raw):
    return raw.decode("utf-8", errors="replace")


def _git_env():
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS", "GIT_CONFIG_COUNT"):
        env.pop(key, None)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
                "LC_ALL": "C", "LANG": "C"})
    return env


def _command(repo, args):
    return ["git", "--no-pager", "--no-lazy-fetch", "--no-replace-objects", "-C", str(repo), "-c", "core.quotepath=false",
            "-c", "color.ui=false", "-c", "log.showSignature=false", *args]


def _run(repo, args, *, input_data=None):
    try:
        result = subprocess.run(_command(repo, args), input=input_data,
                                capture_output=True, timeout=GIT_TIMEOUT,
                                env=_git_env(), shell=False, check=False,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except subprocess.TimeoutExpired as exc:
        raise GitReadError("Git 读取超时") from exc
    except OSError as exc:
        raise GitReadError("无法启动 Git") from exc
    if result.returncode:
        detail = _decode(result.stderr).strip().splitlines()
        raise GitReadError((detail[-1] if detail else "Git 读取失败")[:240])
    return result.stdout


def _parse_raw(raw):
    """Parse --raw -z, including rename/copy paths and full blob IDs."""
    tokens, index, files = raw.split(b"\0"), 0, []
    while index < len(tokens) and tokens[index]:
        header = tokens[index].split()
        if len(header) != 5 or not header[0].startswith(b":"):
            raise GitReadError("无法解析 Git raw 元数据")
        index += 1
        status = _decode(header[4])
        if index >= len(tokens):
            raise GitReadError("Git raw 路径不完整")
        first = _decode(tokens[index]); index += 1
        old_path = None
        if status[0] in "RC":
            old_path = first
            if index >= len(tokens):
                raise GitReadError("Git raw 重命名路径不完整")
            path = _decode(tokens[index]); index += 1
        else:
            path = first
        before_mode, after_mode = _decode(header[0][1:]), _decode(header[1])
        before_object = None if set(header[2]) == {48} else _decode(header[2])
        after_object = None if set(header[3]) == {48} else _decode(header[3])
        files.append({"path": path, "old_path": old_path, "status": status,
                      "before_mode": before_mode, "after_mode": after_mode,
                      "before_object": before_object, "after_object": after_object,
                      "before_blob": before_object if before_mode != "160000" else None,
                      "after_blob": after_object if after_mode != "160000" else None})
    return files


def _parse_numstat(raw):
    """Parse --numstat -z; tabs/newlines inside filenames are not separators."""
    tokens, index, stats = raw.split(b"\0"), 0, {}
    while index < len(tokens) and tokens[index]:
        parts = tokens[index].split(b"\t", 2); index += 1
        if len(parts) != 3:
            raise GitReadError("无法解析 Git numstat")
        added, deleted, raw_path = parts
        old_path = None
        if raw_path:
            path = _decode(raw_path)
        else:
            if index + 1 >= len(tokens):
                raise GitReadError("Git numstat 重命名路径不完整")
            old_path, path = _decode(tokens[index]), _decode(tokens[index + 1])
            index += 2
        try:
            stats[(old_path, path)] = {
                "additions": None if added == b"-" else int(added),
                "deletions": None if deleted == b"-" else int(deleted),
                "binary": added == b"-" or deleted == b"-",
            }
        except ValueError as exc:
            raise GitReadError("Git numstat 行数无效") from exc
    return stats


def _patch(repo, args):
    """Drain Git output with bounded memory, counting all original bytes/hunks."""
    state = {"prefix": bytearray(), "bytes": 0, "hunks": 0, "error": None}
    line_prefix, error_prefix = bytearray(), bytearray()

    def read_stdout(stream):
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                state["bytes"] += len(chunk)
                room = PATCH_LIMIT - len(state["prefix"])
                if room > 0:
                    state["prefix"].extend(chunk[:room])
                pieces = chunk.split(b"\n")
                for i, piece in enumerate(pieces):
                    if len(line_prefix) < 128:
                        line_prefix.extend(piece[:128 - len(line_prefix)])
                    if i < len(pieces) - 1:
                        if HUNK_RE.match(line_prefix):
                            state["hunks"] += 1
                        line_prefix.clear()
            if line_prefix and HUNK_RE.match(line_prefix):
                state["hunks"] += 1
        except OSError as exc:
            state["error"] = type(exc).__name__
        finally:
            stream.close()

    def read_stderr(stream):
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                room = 1024 - len(error_prefix)
                if room > 0:
                    error_prefix.extend(chunk[:room])
        except OSError as exc:
            state["error"] = type(exc).__name__
        finally:
            stream.close()

    try:
        process = subprocess.Popen(_command(repo, args), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=_git_env(), shell=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        reader = threading.Thread(target=read_stdout, args=(process.stdout,), daemon=True)
        error_reader = threading.Thread(target=read_stderr, args=(process.stderr,), daemon=True)
        reader.start(); error_reader.start()
        try:
            code = process.wait(timeout=GIT_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            process.kill(); process.wait(); reader.join(timeout=2); error_reader.join(timeout=2)
            raise GitReadError("Git 补丁读取超时") from exc
        reader.join(timeout=2); error_reader.join(timeout=2)
        if reader.is_alive() or error_reader.is_alive() or state["error"]:
            raise GitReadError("Git 补丁输出未完整读取")
        if code:
            raise GitReadError(_decode(error_prefix).strip()[:240] or "Git 补丁读取失败")
    except OSError as exc:
        raise GitReadError("无法读取 Git 补丁") from exc
    raw = bytes(state["prefix"])
    truncated = state["bytes"] > len(raw)
    if truncated:
        # Keep complete lines, so a cropped line is never presented as a fact.
        raw = raw[:raw.rfind(b"\n") + 1]
    encoding_replaced = False
    try:
        patch = raw.decode('utf-8')
    except UnicodeDecodeError:
        patch = codecs.getincrementaldecoder("utf-8")("replace").decode(raw, final=True)
        encoding_replaced = True
    return {"patch": patch, "bytes_original": state["bytes"], "bytes_kept": len(raw),
            "truncated": truncated, "hunk_count": state["hunks"],
            "hunks": _parse_hunks(patch), "patch_available": True,
            "encoding_replaced": encoding_replaced}


def _parse_hunks(patch):
    hunks, current, old_line, new_line = [], None, None, None
    # Git counts LF-delimited lines, not Python's wider Unicode line separators.
    for line in patch.split('\n'):
        match = HUNK_RE.match(line.encode("utf-8"))
        if match:
            old_line, new_line = int(match[1]), int(match[3])
            current = {"header": line, "old_start": old_line,
                       "old_count": int(match[2]) if match[2] is not None else 1,
                       "new_start": new_line,
                       "new_count": int(match[4]) if match[4] is not None else 1,
                       "lines": []}
            hunks.append(current)
        elif current is not None and line[:1] in ("+", "-", " "):
            prefix = line[0]
            current["lines"].append({"kind": {"+": "addition", "-": "deletion", " ": "context"}[prefix],
                                     "text": line[1:],
                                     "old_line": None if prefix == "+" else old_line,
                                     "new_line": None if prefix == "-" else new_line})
            if prefix != "+": old_line += 1
            if prefix != "-": new_line += 1
        elif current is not None and line.startswith("\\ No newline"):
            current["lines"].append({"kind": "note", "text": line,
                                     "old_line": None, "new_line": None})
    return hunks


def _category(path):
    extension = PurePosixPath(path).suffix.lower()
    return CATEGORIES.get(extension, extension + " 文件" if extension else "无扩展名文件")


def _summary(commits):
    files = [file for commit in commits for file in commit["files"]]
    if not commits:
        return "没有可展示的 Git 提交记录。"
    additions = sum(file["additions"] or 0 for file in files)
    deletions = sum(file["deletions"] or 0 for file in files)
    hunk_counts = [file["hunk_count"] for file in files]
    hunk_text = str(sum(hunk_counts)) if all(value is not None for value in hunk_counts) else "未完整读取"
    categories = Counter(file["category"] for file in files)
    text = f"已读取 {len(commits)} 个提交，涉及 {len(files)} 次文件变更，新增 {additions} 行、删除 {deletions} 行，差异块 {hunk_text}。"
    if categories:
        text += "按扩展名分类：" + "、".join(f"{name} {count}" for name, count in sorted(categories.items())) + "。"
    binary = sum(file["binary"] for file in files)
    truncated = sum(file["truncated"] for file in files)
    if binary: text += f"{binary} 次二进制文件变更不计文本行数。"
    if truncated: text += f"{truncated} 份补丁已截断，行数统计仍来自完整提交。"
    return text + "文件分类不表示改动意图。"


def _result(status, reason, commits=None, skipped=None):
    commits = commits or []
    return {"status": status, "reason": reason, "commits": commits,
            "skipped": skipped or [], "summary": _summary(commits)}


def extract_change(repo: str, commits: list[str], project_root: Path,
                   paths: list[str] | None = None) -> dict:
    """Return Git facts; errors degrade this record without raising to a build.

    project_root locates a relative repo; it need not be inside that repository.
    paths are literal git_path values relative to the target Git worktree root,
    or absolute paths inside that worktree. paths=None means all files; paths=[]
    matches no files. Directories include descendants. Renames match either old
    or new paths. Author dates are ISO-8601 author dates.
    """
    if not commits:
        return _result("no_history", "未登记提交 SHA")
    if not isinstance(repo, str) or not repo.strip():
        return _result("unavailable", "未登记仓库路径")
    try:
        project = Path(project_root).expanduser().resolve()
        configured_repo = Path(repo).expanduser()
        repo_path = (configured_repo if configured_repo.is_absolute() else project / configured_repo).resolve()
        if not repo_path.is_dir():
            return _result("unavailable", "仓库路径不可达")
        root = Path(_decode(_run(repo_path, ["rev-parse", "--show-toplevel"])).strip()).resolve()
        filters = None
        if paths is not None:
            filters = []
            for value in paths:
                path = Path(value)
                absolute = (path if path.is_absolute() else root / path).resolve()
                absolute.relative_to(root)
                filters.append(absolute.relative_to(root).as_posix().rstrip("/"))
    except (GitReadError, OSError, ValueError, TypeError) as exc:
        return _result("unavailable", "仓库或项目路径不可用：" + str(exc)[:240])

    def matches(file):
        if filters is None:
            return True
        candidates = [file["path"], file["old_path"]]
        return any(candidate is not None and (selected in ("", ".") or candidate == selected or candidate.startswith(selected + "/"))
                   for selected in filters for candidate in candidates)

    output, skipped, seen, degraded = [], [], set(), False
    for requested in commits:
        if not isinstance(requested, str) or SHA_RE.fullmatch(requested) is None:
            skipped.append({"input": str(requested)[:80], "reason": "提交必须是 7–40 位十六进制 SHA"})
            degraded = True
            continue
        try:
            sha = _decode(_run(root, ["rev-parse", "--verify", requested + "^{commit}"])).strip()
            if sha in seen:
                skipped.append({"input": requested, "sha": sha, "reason": "重复提交已合并"})
                continue
            seen.add(sha)
            metadata = _run(root, ["show", "-s", "--format=%H%x00%P%x00%s%x00%an%x00%aI", sha]).rstrip(b"\r\n").split(b"\0")
            if len(metadata) != 5:
                raise GitReadError("无法解析提交元数据")
            parents = _decode(metadata[1]).split()
            common = ["--no-ext-diff", "--no-textconv", "--no-color", "--find-renames=50%"]
            if parents:
                diff = ["diff", *common, parents[0], sha]
            else:
                diff = ["diff-tree", "--root", "--no-commit-id", "-r", *common, sha]
            raw_files = _parse_raw(_run(root, [*diff, "--raw", "-z", "--abbrev=40", "--"]))
            stats = _parse_numstat(_run(root, [*diff, "--numstat", "-z", "--"]))
            selected = [file for file in raw_files if matches(file)]
            if filters is not None and not selected:
                skipped.append({"input": requested, "sha": sha, "reason": "该提交未修改筛选路径"})
                continue
            for file in selected:
                key = (file["old_path"], file["path"])
                if key not in stats:
                    raise GitReadError("Git 文件状态与行数统计不一致")
                file.update(stats[key])
                file["category"] = _category(file["path"])
                file["category_source"] = "file-extension"
                literal_paths = list(dict.fromkeys(path for path in (file["old_path"], file["path"]) if path is not None))
                try:
                    file.update(_patch(root, [*diff, "--patch", "--unified=3", "--", *[":(literal)" + path for path in literal_paths]]))
                    degraded = degraded or file["truncated"] or file.get('encoding_replaced', False)
                except GitReadError as exc:
                    file.update({"patch": "", "hunks": [], "hunk_count": None,
                                 "patch_available": False, "patch_error": str(exc),
                                 "bytes_original": None, "bytes_kept": 0, "truncated": False})
                    degraded = True
            hunk_counts = [file["hunk_count"] for file in selected]
            output.append({"sha": sha, "parents": parents, "subject": _decode(metadata[2]),
                           "author": _decode(metadata[3]), "date": _decode(metadata[4]),
                           "comparison": "first-parent" if parents else "empty-tree",
                           "files": selected,
                           "totals": {"files": len(selected),
                                      "additions": sum(file["additions"] or 0 for file in selected),
                                      "deletions": sum(file["deletions"] or 0 for file in selected),
                                      "hunks": sum(hunk_counts) if all(n is not None for n in hunk_counts) else None}})
        except (GitReadError, OSError, ValueError, TypeError, IndexError) as exc:
            skipped.append({"input": requested, "reason": "提交读取失败：" + str(exc)[:240]})
            degraded = True
    if output:
        return _result("partial" if degraded else "available", "部分提交或补丁未完整读取，详见 skipped 与文件截断标记" if degraded else "已读取实际 Git 提交及差异", output, skipped)
    if degraded:
        return _result("unavailable", "没有可读取的指定提交", skipped=skipped)
    return _result("no_history", "指定提交没有修改筛选路径", skipped=skipped)

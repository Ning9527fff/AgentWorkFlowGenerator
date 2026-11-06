#!/usr/bin/env python3
"""检查生成的协作规范：链接有效、模板无残留、路由单向无环、规范文件均可达。

用法（在项目根目录或传入根目录）：
  python3 check_docs.py [根目录]                     检查规范
  python3 check_docs.py [根目录] --init [--force]    按默认规则建立层级映射（生成规范时运行一次）
  python3 check_docs.py [根目录] --set 路径 层级      设置单个文件的层级
  python3 check_docs.py [根目录] --update            文件改名、移动、删除或修改后刷新映射
退出码：0 表示没有错误（可能有警告），1 表示存在错误或命令失败。

规范文件：根目录 AGENTS.md 与 .agents/ 下的 Markdown，不含 agentRecord/ 中的任务记录。

层级（数字越小越靠上游）记录在 .agents/scripts/levels.json，以相对路径为键，
每项保存层级与文件内容的 MD5。检查时按路径查层级；路径查不到时，用 MD5 在映射中
查找改名或移动前的条目。MD5 只用于识别改名，不作安全用途。--init 的默认层级：
  0 AGENTS.md
  1 */entry.md                     语言入口
  2 */coding-index.md、*/SKILL.md  编码索引与审查 skill
  3 其余规范文件                    专题与记录索引

路由链接：路由表（表头含“按需阅读”）最后一列中的链接，以及“另见 [..](..)”。
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

ROUTE_HEADER = "按需阅读"
INDEX_LINE_LIMIT = 200
MAPPING_PATH = Path(".agents/scripts/levels.json")
MAPPING_VERSION = 1
LEVELS = range(0, 4)

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SEE_ALSO_RE = re.compile(r"另见\s*\[[^\]]*\]\(([^)]+)\)")
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
CONDITION_RE = re.compile(r"<!--\s*/?条件")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN_RE = re.compile(r"`[^`]*`")


def find_root(arg):
    if arg:
        return Path(arg).resolve()

    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        sys.exit("无法确定项目根目录：请在 git 仓库中运行，或传入根目录路径")

    return Path(out.stdout.strip())


def is_record(rel):
    """agentRecord/ 中除 README.md 以外的文件属于任务记录，不是规范文件。"""
    if "agentRecord" not in rel.parts:
        return False

    return rel.name != "README.md"


def default_level(rel):
    if rel.as_posix() == "AGENTS.md":
        return 0
    if rel.name == "entry.md":
        return 1
    if rel.name in ("coding-index.md", "SKILL.md"):
        return 2
    return 3


def collect_files(root):
    """返回 (全部 Markdown 文件, 规范文件集合)，路径均相对于根目录。"""
    files = []
    if (root / "AGENTS.md").exists():
        files.append(Path("AGENTS.md"))

    agents = root / ".agents"
    if agents.is_dir():
        files += sorted(p.relative_to(root) for p in agents.rglob("*.md"))

    return files, {f for f in files if not is_record(f)}


def file_md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def strip_code(lines):
    """去掉围栏代码块和行内代码，避免把示例当作链接或残留。"""
    result = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            result.append("")
            continue

        result.append("" if in_fence else CODE_SPAN_RE.sub("", line))

    return result


def link_target(raw):
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        target = target[1:target.index(">")]
    else:
        target = target.split()[0] if target.split() else ""

    if not target or target.startswith("#"):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return None

    return unquote(target.split("#", 1)[0])


def route_lines(lines):
    """返回路由表数据行的行号集合，以及路由表被空行断开的位置。"""
    rows = set()
    breaks = []
    in_table = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table and not stripped:
                nxt = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
                if nxt.startswith("|") and ROUTE_HEADER not in nxt:
                    breaks.append(i)
            in_table = False
            continue

        if ROUTE_HEADER in stripped:
            in_table = True
            continue

        if in_table and not re.fullmatch(r"\|[\s:|-]+\|?", stripped):
            rows.add(i)

    return rows, breaks


def last_cell(line):
    cells = line.strip().strip("|").split("|")
    return cells[-1] if cells else ""


# ---------- 层级映射 ----------

class MappingError(Exception):
    pass


def load_mapping(root):
    path = root / MAPPING_PATH
    if not path.exists():
        raise MappingError(f"缺少层级映射 {MAPPING_PATH.as_posix()}：运行 --init 建立")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MappingError(f"{MAPPING_PATH.as_posix()} 解析失败：{exc}") from exc

    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict) or data.get("version") != MAPPING_VERSION:
        raise MappingError(f"{MAPPING_PATH.as_posix()} 格式不符：需要 version={MAPPING_VERSION} 与 files 字段")

    for key, entry in files.items():
        level = entry.get("level") if isinstance(entry, dict) else None
        if type(level) is not int or level not in LEVELS or not isinstance(entry.get("md5"), str):
            raise MappingError(f"{MAPPING_PATH.as_posix()} 中 {key} 的条目不完整：需要 level（0-3）与 md5")

    return files


def save_mapping(root, files):
    path = root / MAPPING_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": MAPPING_VERSION, "files": dict(sorted(files.items()))}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_mapping(files):
    for key, entry in sorted(files.items()):
        print(f"  {entry['level']}  {key}")


def cmd_init(root, force):
    if (root / MAPPING_PATH).exists() and not force:
        print(f"{MAPPING_PATH.as_posix()} 已存在；需要重建时加 --force")
        return 1

    _, specs = collect_files(root)
    files = {
        rel.as_posix(): {"level": default_level(rel), "md5": file_md5(root / rel)}
        for rel in specs
    }
    save_mapping(root, files)
    print(f"已写入 {MAPPING_PATH.as_posix()}，共 {len(files)} 个规范文件。层级与规划不符的，用 --set 调整：")
    print_mapping(files)
    return 0


def cmd_set(root, raw_path, level):
    if level not in LEVELS:
        print(f"层级必须在 0-3 之间：{level}")
        return 1

    rel = Path(raw_path)
    _, specs = collect_files(root)
    if rel not in specs:
        print(f"不是规范文件：{raw_path}（规范文件为 AGENTS.md 与 .agents/ 下除任务记录外的 Markdown）")
        return 1

    try:
        files = load_mapping(root)
    except MappingError as exc:
        print(exc)
        return 1

    files[rel.as_posix()] = {"level": level, "md5": file_md5(root / rel)}
    save_mapping(root, files)
    print(f"已设置 {rel.as_posix()} 的层级为 {level}")
    return 0


def cmd_update(root):
    try:
        files = load_mapping(root)
    except MappingError as exc:
        print(exc)
        return 1

    _, specs = collect_files(root)
    current = {rel.as_posix(): file_md5(root / rel) for rel in specs}
    by_md5 = {v["md5"]: k for k, v in files.items() if k not in current}
    result = {}
    unregistered = []

    for key, md5 in sorted(current.items()):
        if key in files:
            if files[key]["md5"] != md5:
                print(f"已刷新 MD5：{key}")
            result[key] = {"level": files[key]["level"], "md5": md5}
        elif md5 in by_md5:
            old = by_md5.pop(md5)
            result[key] = {"level": files[old]["level"], "md5": md5}
            print(f"识别为改名或移动：{old} → {key}（层级 {files[old]['level']}）")
        else:
            unregistered.append(key)

    for old in sorted(by_md5.values()):
        print(f"已删除映射：{old}（文件不存在，且没有内容相同的新文件）")

    save_mapping(root, result)
    for key in unregistered:
        print(f"未登记：{key}（新文件，或改名的同时修改了内容），用 --set {key} 层级 登记")

    return 1 if unregistered else 0


# ---------- 检查 ----------

class Checker:
    def __init__(self, root):
        self.root = root
        self.errors = []
        self.warnings = []
        self.levels = {}

    def error(self, rel, lineno, msg):
        self.errors.append(f"{rel.as_posix()}:{lineno}：{msg}")

    def warn(self, rel, lineno, msg):
        self.warnings.append(f"{rel.as_posix()}:{lineno}：{msg}")

    def level(self, rel):
        return self.levels.get(rel, default_level(rel))

    def resolve(self, rel, target):
        path = (self.root / rel).parent / target
        try:
            return path.resolve().relative_to(self.root)
        except ValueError:
            return None

    def run(self):
        files, specs = collect_files(self.root)
        if Path("AGENTS.md") not in specs:
            self.errors.append("缺少根入口 AGENTS.md")

        self.resolve_levels(specs)
        routes = defaultdict(set)
        for rel in files:
            self.check_file(rel, specs, routes)

        self.check_cycles(specs, routes)
        self.check_reachable(specs, routes)

    def resolve_levels(self, specs):
        """按路径查层级；查不到时按 MD5 识别改名；内容变化只汇总提示。"""
        try:
            files = load_mapping(self.root)
        except MappingError as exc:
            self.errors.append(str(exc))
            return

        spec_keys = {rel.as_posix() for rel in specs}
        missing = {k: v for k, v in files.items() if k not in spec_keys}
        by_md5 = {v["md5"]: k for k, v in missing.items()}
        stale = []
        for rel in sorted(specs):
            key = rel.as_posix()
            md5 = file_md5(self.root / rel)
            entry = files.get(key)

            if entry is not None:
                self.levels[rel] = entry["level"]
                if entry["md5"] != md5:
                    stale.append(key)
                continue

            old = by_md5.pop(md5, None)
            if old is not None:
                self.levels[rel] = files[old]["level"]
                self.errors.append(f"{key}：文件已从 {old} 改名或移动，运行 --update 更新映射")
            else:
                self.errors.append(f"{key}：未登记的规范文件，用 --set {key} 层级 登记")

        for key in sorted(by_md5.values()):
            self.errors.append(f"{key}：映射中的文件不存在，运行 --update 删除该条目")

        if stale:
            self.warnings.append(
                f"{len(stale)} 个规范文件内容已修改，映射中的 MD5 未刷新；运行 --update 刷新，否则之后改名时无法识别："
                + "、".join(stale)
            )

    def check_file(self, rel, specs, routes):
        raw = (self.root / rel).read_text(encoding="utf-8").splitlines()
        lines = strip_code(raw)
        is_spec = rel in specs
        level = self.level(rel)
        rows, breaks = route_lines(lines)

        for i in breaks:
            self.error(rel, i + 1, "路由表被空行断开，空行后的行不会被识别为路由")

        for i, line in enumerate(lines, 1):
            for match in PLACEHOLDER_RE.findall(line):
                self.error(rel, i, f"模板占位符未替换：{match}")
            if CONDITION_RE.search(line):
                self.error(rel, i, "模板条件标记未删除")

        if is_spec and level >= 3 and rows:
            self.error(rel, min(rows) + 1, "专题文件不应包含路由表")

        if is_spec and level <= 2 and rel.name != "SKILL.md" and len(raw) > INDEX_LINE_LIMIT:
            self.warn(rel, len(raw), f"索引文件超过 {INDEX_LINE_LIMIT} 行，考虑拆出下一级索引")

        if is_spec and rel.name == "SKILL.md":
            self.check_frontmatter(rel, raw)

        for i, line in enumerate(lines):
            route_targets = set()
            if i in rows:
                route_targets |= set(LINK_RE.findall(last_cell(line)))
            route_targets |= set(SEE_ALSO_RE.findall(line))

            for raw_target in LINK_RE.findall(line):
                target = link_target(raw_target)
                if target is None:
                    continue

                dest = self.resolve(rel, target)
                if dest is None or not (self.root / dest).exists():
                    self.error(rel, i + 1, f"链接目标不存在：{target}")
                    continue

                if not is_spec or dest not in specs:
                    continue

                if raw_target in route_targets:
                    routes[rel].add(dest)
                    if self.level(dest) < level:
                        self.error(rel, i + 1, f"路由指回上游（{level} → {self.level(dest)}）：{target}")
                elif self.level(dest) <= 1 and level > self.level(dest):
                    self.warn(rel, i + 1, f"正文链接指向上游入口，确认它不是阅读指令：{target}")

    def check_frontmatter(self, rel, raw):
        if not raw or raw[0].strip() != "---":
            self.error(rel, 1, "SKILL.md 缺少 frontmatter")
            return

        try:
            end = raw[1:].index("---") + 1
        except ValueError:
            self.error(rel, 1, "SKILL.md 的 frontmatter 未闭合")
            return

        keys = {line.split(":", 1)[0].strip() for line in raw[1:end] if ":" in line}
        for key in ("name", "description"):
            if key not in keys:
                self.error(rel, 1, f"SKILL.md 的 frontmatter 缺少 {key}")

    def check_cycles(self, specs, routes):
        """Tarjan 强连通分量；每个包含多个文件的分量或自环都是一个循环。"""
        index = {}
        low = {}
        stack = []
        on_stack = set()
        counter = [0]
        components = []

        def visit(node):
            index[node] = low[node] = counter[0]
            counter[0] += 1
            stack.append(node)
            on_stack.add(node)

            for nxt in routes.get(node, ()):
                if nxt not in index:
                    visit(nxt)
                    low[node] = min(low[node], low[nxt])
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])

            if low[node] == index[node]:
                comp = []
                while True:
                    item = stack.pop()
                    on_stack.discard(item)
                    comp.append(item)
                    if item == node:
                        break
                components.append(comp)

        for node in sorted(specs):
            if node not in index:
                visit(node)

        for comp in components:
            if len(comp) > 1 or comp[0] in routes.get(comp[0], ()):
                names = " → ".join(sorted(p.as_posix() for p in comp))
                self.errors.append(f"路由循环：{names}")

    def check_reachable(self, specs, routes):
        start = Path("AGENTS.md")
        if start not in specs:
            return

        seen = {start}
        queue = [start]
        while queue:
            node = queue.pop()
            for nxt in routes.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

        for rel in sorted(specs - seen):
            self.errors.append(f"{rel.as_posix()}：从 AGENTS.md 沿路由无法到达")


def cmd_check(root):
    checker = Checker(root)
    checker.run()

    for msg in checker.errors:
        print(f"错误 {msg}")
    for msg in checker.warnings:
        print(f"警告 {msg}")
    print(f"检查完成：{len(checker.errors)} 个错误，{len(checker.warnings)} 个警告")

    return 1 if checker.errors else 0


def main():
    parser = argparse.ArgumentParser(description="检查协作规范的链接、层级与路由结构")
    parser.add_argument("root", nargs="?", help="项目根目录，默认为当前 git 仓库根目录")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--init", action="store_true", help="按默认规则建立层级映射")
    group.add_argument("--set", nargs=2, metavar=("路径", "层级"), help="设置单个规范文件的层级")
    group.add_argument("--update", action="store_true", help="刷新映射：处理改名、移动、删除与内容修改")
    parser.add_argument("--force", action="store_true", help="与 --init 一起使用，覆盖已有映射")
    args = parser.parse_args()

    root = find_root(args.root)
    if args.init:
        return cmd_init(root, args.force)
    if args.set:
        try:
            level = int(args.set[1])
        except ValueError:
            print(f"层级必须是整数：{args.set[1]}")
            return 1
        return cmd_set(root, args.set[0], level)
    if args.update:
        return cmd_update(root)

    return cmd_check(root)


if __name__ == "__main__":
    sys.exit(main())

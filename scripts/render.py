#!/usr/bin/env python3
"""按渲染配置把 templates/ 中的模板生成为目标项目的协作规范。

用法（在任意目录运行）：
  python3 render.py 配置.json 目标目录 --plan          列出将生成的文件及处理方式，不写入
  python3 render.py 配置.json 目标目录 --print 路径    输出单个生成文件的内容，不写入（用于预览或合并）
  python3 render.py 配置.json 目标目录                 写入文件，建立层级映射并运行 check_docs.py

配置格式见 templates/README.md。目标目录中已存在的文件须在配置的 replace 或 skip 中声明，
否则拒绝写入。配置中的 @@路径@@（相对目标项目根目录）在每个生成文件中换算为相对于该文件的路径。
退出码：0 成功；1 配置错误、文件冲突或检查有错误；2 用法错误。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
TEMPLATES = SCRIPTS_DIR.parent / "templates"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_docs import default_level  # noqa: E402  层级规则只在 check_docs.py 中维护

COPIED_SCRIPTS = ("snapshot.sh", "check_docs.py")
LEVELS_PATH = ".agents/scripts/levels.json"
CONFIG_COPY = ".agents/scripts/workflow-config.json"

TIERS = ("轻量", "标准", "严格")
# 阻断级别由 blocking_levels 按档位和风格审查模式确定。
BLOCKING_TO_P1 = "P0、P1"
BLOCKING_TO_P2 = "P0、P1、P2"
DEFAULT_GATE = {
    "轻量": "整体完成独立审查后",
    "标准": "每批任务完成独立审查后",
    "严格": "每个小任务完成独立审查后",
}
PENDING = "待确认"

# 风格审查模式与档位相互独立：建议 = 风格问题不阻断；必改 = 风格问题也阻断。
STYLE_REVIEWS = ("建议", "必改")
DEFAULT_STYLE_REVIEW = {"轻量": "建议", "标准": "必改", "严格": "必改"}
STYLE_SCOPE = {
    True: "本次差异新增或修改的行（含测试代码）",
    False: "本次差异新增或修改的行（不含测试代码）",
}

TOOLS = ("claude", "codex")
INHERIT = "继承"
# 可配置模型的角色；architect 是主会话，只写入建议，不生成 agent 定义。
ROLES = ("architect", "coder", "reviewer")
# Claude Code 审查 agent 不给 Edit、Write；Coder 用默认的全部工具。
CLAUDE_REVIEW_TOOLS = "Read, Grep, Glob, Bash"
MODEL_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]+$")

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COND_RE = re.compile(r"^<!--\s*条件:\s*(.+?)\s*-->\n(.*?)^<!--\s*/条件\s*-->\n", re.S | re.M)
COND_MARK_RE = re.compile(r"<!--\s*/?条件")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
LINK_MARK_RE = re.compile(r"@@([^@\n]+)@@")

LANG_TOPICS = ("style", "toolchain")
OPTIONAL_TOPICS = {
    "high-risk-areas": "有高风险区域",
    "domain-checks": "有领域要点",
    "migration-comparison": "迁移项目",
}

# 表格行字段：(配置键, 必填字段)
TABLE_LISTS = {
    "high_risk_areas": ("area", "code", "invariants", "source"),
    "domain_checks": ("capability", "checks", "source"),
}


class ConfigError(Exception):
    pass


# ---------- 配置 ----------

def load_config(path):
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"无法读取配置 {path}：{exc}") from exc

    if not isinstance(cfg, dict):
        raise ConfigError("配置顶层须为 JSON 对象")

    errors = []
    validate_basics(cfg, errors)
    validate_languages(cfg, path.parent, errors)
    validate_lists(cfg, errors)
    if errors:
        raise ConfigError("配置有误：\n" + "\n".join(f"  - {e}" for e in errors))

    cfg.setdefault("gate", DEFAULT_GATE[cfg["tier"]])
    cfg.setdefault("style_review", DEFAULT_STYLE_REVIEW[cfg["tier"]])
    cfg.setdefault("style_review_tests", True)
    return cfg


def validate_basics(cfg, errors):
    if not NAME_RE.match(str(cfg.get("project", ""))):
        errors.append("project 须为小写字母、数字和连字符，如 my-app")

    if cfg.get("tier") not in TIERS:
        errors.append(f"tier 须为 {'、'.join(TIERS)} 之一")

    if cfg.get("style_review", STYLE_REVIEWS[0]) not in STYLE_REVIEWS:
        errors.append(f"style_review 须为 {'、'.join(STYLE_REVIEWS)} 之一")
    if not isinstance(cfg.get("style_review_tests", True), bool):
        errors.append("style_review_tests 须为 true 或 false")

    for key in ("replace", "skip", "existing_collab", "contract_docs", *TABLE_LISTS):
        if not isinstance(cfg.setdefault(key, []), list):
            errors.append(f"{key} 须为数组")

    tools = cfg.setdefault("tools", [])
    if not isinstance(tools, list) or any(x not in TOOLS for x in tools):
        errors.append(f"tools 须为数组，取值 {'、'.join(TOOLS)}")

    models = cfg.setdefault("models", {})
    if not isinstance(models, dict):
        errors.append("models 须为对象")
    else:
        for tool, roles in models.items():
            if tool not in TOOLS or not isinstance(roles, dict):
                errors.append(f"models.{tool}：键须为 {'、'.join(TOOLS)}，值为“角色: 模型”对象")
                continue
            for role, model in roles.items():
                if role not in ROLES:
                    errors.append(f"models.{tool}.{role}：角色须为 {'、'.join(ROLES)}")
                elif not isinstance(model, str) or not MODEL_RE.match(model):
                    errors.append(f"models.{tool}.{role}：模型名只能包含字母、数字和 . _ : - [ ]")

    migration = cfg.get("migration")
    if migration is not None and (not isinstance(migration, dict) or not migration.get("plan")):
        errors.append("migration 须为对象，并包含 plan（迁移规划的说明与链接）")


def validate_languages(cfg, config_dir, errors):
    langs = cfg.get("languages")
    if not isinstance(langs, list) or not langs:
        errors.append("languages 至少包含一种语言")
        return

    seen = set()
    for i, lang in enumerate(langs):
        where = f"languages[{i}]"
        if not isinstance(lang, dict):
            errors.append(f"{where} 须为对象")
            continue

        for key in ("name", "id", "dirs"):
            if not lang.get(key):
                errors.append(f"{where} 缺少 {key}")

        if lang.get("id") and not NAME_RE.match(lang["id"]):
            errors.append(f"{where}.id 须为小写字母、数字和连字符")
        if lang.get("id") in seen:
            errors.append(f"{where}.id 重复：{lang['id']}")
        seen.add(lang.get("id"))

        rules_file = lang.pop("style_rules_file", None)
        if rules_file:
            try:
                lang["style_rules"] = (config_dir / rules_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                errors.append(f"{where}.style_rules_file 无法读取：{exc}")

        if not lang.get("style_rules"):
            errors.append(f"{where}：须提供 style_rules 或 style_rules_file（所有档位都生成文字风格规则）")

        for item in lang.setdefault("plan_routes", []):
            if not isinstance(item, dict) or not all(item.get(k) for k in ("label", "title", "path")):
                errors.append(f"{where}.plan_routes 每项须包含 label、title、path")


def validate_lists(cfg, errors):
    for key, fields in TABLE_LISTS.items():
        for i, item in enumerate(cfg[key]):
            if not isinstance(item, dict) or not all(item.get(f) for f in fields):
                errors.append(f"{key}[{i}] 须包含 {'、'.join(fields)}")
                continue
            for f in fields:
                if "|" in item[f] or "\n" in item[f]:
                    errors.append(f"{key}[{i}].{f} 是表格单元格，不能包含 | 或换行")

    for i, doc in enumerate(cfg["contract_docs"]):
        if not isinstance(doc, dict) or not all(doc.get(k) for k in ("name", "path", "scope")):
            errors.append(f"contract_docs[{i}] 须包含 name、path、scope")


def check_paths(cfg, target):
    """配置引用的仓库文件必须存在；生成的规范文件不在此检查。"""
    paths = [d["path"] for d in cfg["contract_docs"]]
    for lang in cfg["languages"]:
        paths += [r["path"] for r in lang["plan_routes"]]
    for text in iter_strings(cfg):
        paths += LINK_MARK_RE.findall(text)

    missing = []
    for rel in sorted(set(paths)):
        full = (target / rel).resolve()
        if not full.is_relative_to(target.resolve()) or not full.exists():
            missing.append(rel)

    if missing:
        raise ConfigError("配置引用的文件在目标项目中不存在：\n" + "\n".join(f"  - {m}" for m in missing))


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_strings(v)


def blocking_levels(cfg):
    """本项目的阻断级别。

    风格必改时风格类 P3 会阻断；阻断线若停在 P1，更严重的 P2 反而放行，所以必改时至少到 P2。
    """
    if cfg["tier"] == "轻量" and cfg["style_review"] == "建议":
        return BLOCKING_TO_P1
    return BLOCKING_TO_P2


def conditions(cfg):
    conds = {f"档位={cfg['tier']}", "多语言" if len(cfg["languages"]) > 1 else "单语言"}
    if cfg["high_risk_areas"]:
        conds.add("有高风险区域")
        if cfg["tier"] == "轻量":
            conds.add("轻量升档")
    if cfg["domain_checks"]:
        conds.add("有领域要点")
    if cfg.get("migration"):
        conds.add("迁移项目")
    if cfg["existing_collab"]:
        conds.add("有已有协作文件")
    if "claude" in cfg["tools"]:
        conds.add("使用Claude")
    if "codex" in cfg["tools"]:
        conds.add("使用Codex")

    style = f"风格{cfg['style_review']}"
    conds.add(style)
    if cfg["tier"] != "严格":
        # 严格档另设风格审查职能；其余档位由代码审查职能核对风格
        conds.add(f"代码审查{style}")

    if "轻量升档" in conds and blocking_levels(cfg) == BLOCKING_TO_P1:
        # 升档后按标准档的阈值阻断，比本项目平时多出 P2
        conds.add("升档提高阻断")
    return conds


# ---------- 生成清单 ----------

def plan_files(cfg, conds):
    """返回 (目标路径, 模板, 语言)；生成规则与 templates/README.md 的默认目录表一致。"""
    langs = cfg["languages"]
    files = [("AGENTS.md", "root-entry.md", langs[0])]

    for lang in langs:
        base = f".agents/{lang['id']}"
        if len(langs) > 1:
            files.append((f"{base}/entry.md", "lang-entry.md", lang))
        files.append((f"{base}/coding-index.md", "coding-index.md", lang))
        for topic in LANG_TOPICS:
            files.append((f"{base}/{topic}.md", f"topics/{topic}.md", lang))

    for template in sorted((TEMPLATES / "topics").glob("*.md")):
        name = template.stem
        needed = OPTIONAL_TOPICS.get(name)
        if name in LANG_TOPICS or (needed and needed not in conds):
            continue
        files.append((f".agents/references/{name}.md", f"topics/{name}.md", None))

    for template, name in skill_list(cfg, conds):
        files.append((f".agents/skills/{cfg['project']}-{name}/SKILL.md", template, None))

    files.append((".agents/decisions/README.md", "decisions/README.md", None))
    files.append((".agents/decisions/_template.md", "decisions/_template.md", None))
    files.append((".agents/agentRecord/README.md", "agent-record/README.md", None))
    files.append((".agents/agentRecord/_template.md", "agent-record/_template.md", None))
    files.append((".agents/agentRecord/_contract-template.md", "agent-record/_contract-template.md", None))
    files.append((".agents/agentRecord/_autonomous-template.md", "agent-record/_autonomous-template.md", None))

    if "claude" in cfg["tools"]:
        files.append(("CLAUDE.md", "tools/CLAUDE.md", None))
    for agent in tool_agents(cfg, conds):
        files.append((agent["dest"], agent["template"], agent))
    return files


def skill_list(cfg, conds):
    """返回 (模板, skill 名后缀)：Coder 与各审查 skill。"""
    tier = cfg["tier"]
    skills = [("roles/coder.md", "coder"),
              ("review/code-review.md", "code-review"),
              ("review/behavior-verification.md", "behavior-verification")]
    if tier == "轻量":
        skills.append(("review/single-reviewer.md", "review"))
    if tier != "轻量" or "轻量升档" in conds:
        skills.append(("review/coordinator.md", "review-coordinator"))
    if tier == "严格":
        skills.append(("review/style-review.md", "style-review"))
    return skills


def model_of(cfg, tool, role):
    return cfg["models"].get(tool, {}).get(role) or INHERIT


def tool_agents(cfg, conds):
    """子 agent 定义：Coder 与审查职能各一个。协调者由主会话担任，不生成定义。"""
    agents = []
    for template, suffix in skill_list(cfg, conds):
        if suffix == "review-coordinator":
            continue
        name = f"{cfg['project']}-{suffix}"
        role = "coder" if suffix == "coder" else "reviewer"
        for tool in cfg["tools"]:
            claude = tool == "claude"
            agents.append({
                "tool": tool, "name": name, "role": role,
                "skill": f".agents/skills/{name}/SKILL.md",
                "dest": f".claude/agents/{name}.md" if claude else f".codex/agents/{name}.toml",
                "template": "tools/claude-agent.md" if claude else "tools/codex-agent.toml",
                "description": read_description(template, cfg["project"]),
                "model": model_of(cfg, tool, role),
            })
    return agents


def read_description(template, project):
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+)$", text, re.M)
    return match.group(1).replace("{{PROJECT}}", project).strip() if match else project


def quoted(value):
    """JSON 字符串同时是合法的 YAML 双引号字符串和 TOML 基本字符串。"""
    return json.dumps(value, ensure_ascii=False)


def agent_values(agent):
    model = agent["model"]
    if agent["tool"] == "claude":
        return {
            "AGENT_NAME": agent["name"],
            "AGENT_DESCRIPTION": quoted(agent["description"]),
            "AGENT_MODEL_LINE": f"model: {'inherit' if model == INHERIT else model}",
            "AGENT_TOOLS_LINE": "" if agent["role"] == "coder" else f"tools: {CLAUDE_REVIEW_TOOLS}",
            "AGENT_SKILL_LINK": f"@@{agent['skill']}@@",
        }
    return {
        "AGENT_NAME_TOML": quoted(agent["name"]),
        "AGENT_DESCRIPTION": quoted(agent["description"]),
        "AGENT_MODEL_LINE": "" if model == INHERIT else f"model = {quoted(model)}",
        "AGENT_SKILL_PATH": agent["skill"],
    }


def agent_rows(cfg, conds, tool):
    names = {"coder": "Coder", "reviewer": "审查职能"}
    return "\n".join(
        f"| `{a['name']}` | {names[a['role']]} | {a['model']} |"
        for a in tool_agents(cfg, conds) if a["tool"] == tool
    )


def other_outputs():
    """非模板产物：复制的脚本、层级映射和配置副本。"""
    return [f".agents/scripts/{name}" for name in COPIED_SCRIPTS] + [LEVELS_PATH, CONFIG_COPY]


def statuses(cfg, target, dests):
    replace, skip = set(cfg["replace"]), set(cfg["skip"])
    result = {}
    for dest in dests:
        if not (target / dest).exists():
            result[dest] = "新建"
        elif dest in replace:
            result[dest] = "替换"
        elif dest in skip:
            result[dest] = "跳过"
        else:
            result[dest] = "冲突"
    return result


# ---------- 渲染 ----------

def resolve_links(text, dest):
    base = os.path.dirname(dest) or "."
    return LINK_MARK_RE.sub(lambda m: os.path.relpath(m.group(1), base), text)


def table_rows(items, fields):
    return "\n".join("| " + " | ".join(item[f] for f in fields) + " |" for item in items)


def dirs_text(lang):
    return "、".join(f"`{d}`" for d in lang["dirs"])


def values(cfg, lang, conds):
    """占位符的值；@@路径@@ 在 render 中按目标文件换算。"""
    langs = cfg["languages"]
    migration = cfg.get("migration") or {}
    vals = {
        "PROJECT": cfg["project"],
        "TIER": cfg["tier"],
        "GATE": cfg["gate"],
        "BLOCKING_LEVELS": blocking_levels(cfg),
        "STYLE_SCOPE": STYLE_SCOPE[cfg["style_review_tests"]],
        "CONTRACT_DOCS": "\n".join(
            f"- [{d['name']}](@@{d['path']}@@)：{d['scope']}" for d in cfg["contract_docs"]
        ) or f"- {PENDING}：扫描未找到业务契约文档；需要时由 Architect 向用户确认，确认后补入本页",
        "LANG_ROUTES": "\n".join(
            f"| {l['name']} 代码开发、测试、迁移或运行配置（{dirs_text(l)}） | [{l['name']} 入口](@@.agents/{l['id']}/entry.md@@) |"
            for l in langs
        ),
        "LANG_INDEX_ROUTES": "\n".join(
            f"| {l['name']} 改动的编码规范 | [{l['name']} 编码索引](@@.agents/{l['id']}/coding-index.md@@) |"
            for l in langs
        ),
        "HIGH_RISK_AREAS": table_rows(cfg["high_risk_areas"], TABLE_LISTS["high_risk_areas"]),
        "DOMAIN_CHECKS": table_rows(cfg["domain_checks"], TABLE_LISTS["domain_checks"]),
        "MIGRATION_PLAN": migration.get("plan", ""),
        "MIGRATION_TEST_CMD": migration.get("test_cmd") or PENDING,
        "EXISTING_COLLAB": "\n".join(cfg["existing_collab"]),
        # 主会话的模型由用户启动会话时选择，这里只是建议
        "CLAUDE_ARCHITECT_MODEL": cfg["models"].get("claude", {}).get("architect") or "未指定",
        "CODEX_ARCHITECT_MODEL": cfg["models"].get("codex", {}).get("architect") or "未指定",
        "CLAUDE_AGENT_ROWS": agent_rows(cfg, conds, "claude"),
        "CODEX_AGENT_ROWS": agent_rows(cfg, conds, "codex"),
    }

    if lang is not None and "tool" in lang:
        # plan_files 对 agent 定义传入的是 agent 描述而不是语言
        vals.update(agent_values(lang))
        return vals

    if lang is not None:
        vals.update({
            "LANG": lang["name"],
            "LANG_ID": lang["id"],
            "LANG_DIRS": dirs_text(lang),
            "FORMAT_CMD": lang.get("format_cmd") or PENDING,
            "LINT_CMD": lang.get("lint_cmd") or PENDING,
            "TEST_CMD": lang.get("test_cmd") or PENDING,
            "BUILD_CMD": lang.get("build_cmd") or PENDING,
            "STYLE_TOOLS": lang.get("style_tools") or f"- {PENDING}",
            "STYLE_RULES": lang.get("style_rules", ""),
            "PLAN_ROUTES": "\n".join(
                f"| {r['label']} | [{r['title']}](@@{r['path']}@@) |" for r in lang["plan_routes"]
            ),
        })

    return vals


def render(template, dest, vals, conds):
    text = (TEMPLATES / template).read_text(encoding="utf-8")

    def keep(match):
        # “档位=标准,严格”中逗号后的档位名省略了“档位=”前缀
        wanted = {c.strip() for c in match.group(1).split(",")}
        wanted |= {f"档位={c}" for c in wanted if c in TIERS}
        return match.group(2) if wanted & conds else ""

    text = COND_RE.sub(keep, text)
    if COND_MARK_RE.search(text):
        raise ConfigError(f"{template}：条件标记格式错误（须各占一行、成对出现、不嵌套）")

    unknown = sorted(set(PLACEHOLDER_RE.findall(text)) - vals.keys())
    if unknown:
        raise ConfigError(f"{template} → {dest}：以下占位符没有值：{'、'.join(unknown)}")

    for key, val in vals.items():
        val = resolve_links(val, dest)
        if val == "":
            # 空值连同所在行一起删除，避免表格被空行断开
            text = re.sub(r"^[ \t]*\{\{%s\}\}[ \t]*\n" % key, "", text, flags=re.M)
        text = text.replace("{{%s}}" % key, val)

    return text


def render_all(cfg, conds):
    return {
        dest: render(template, dest, values(cfg, lang, conds), conds)
        for dest, template, lang in plan_files(cfg, conds)
    }


# ---------- 命令 ----------

def print_plan(rendered, status):
    print(f"{'处理':<4} {'层级':<4} 路径")
    for dest in list(rendered) + other_outputs():
        spec = dest == "AGENTS.md" or (dest.startswith(".agents/") and dest.endswith(".md"))
        level = f"L{default_level(Path(dest))}" if spec else "-"
        print(f"{status[dest]:<4} {level:<4} {dest}")

    conflicts = [d for d, s in status.items() if s == "冲突"]
    if conflicts:
        print("\n以下文件已存在，须在配置的 replace 或 skip 中声明：")
        for dest in conflicts:
            print(f"  - {dest}")
    if status.get("CLAUDE.md") == "跳过":
        print("\n提示：保留了已有的 CLAUDE.md，需要在其中加入一行 @AGENTS.md，Claude Code 才会读取项目入口。")
    if status.get("AGENTS.md") == "跳过":
        print("\n提示：保留了已有的 AGENTS.md，需要手工把新生成的路由合并进去（可用 --print AGENTS.md 查看）。")

    return 1 if conflicts else 0


def write_all(cfg, target, rendered, status):
    for dest, text in rendered.items():
        if status[dest] in ("新建", "替换"):
            path = target / dest
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    scripts = target / ".agents" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in COPIED_SCRIPTS:
        if status[f".agents/scripts/{name}"] in ("新建", "替换"):
            shutil.copy2(SCRIPTS_DIR / name, scripts / name)

    if status[CONFIG_COPY] in ("新建", "替换"):
        saved = {k: v for k, v in cfg.items() if k not in ("replace", "skip")}
        (target / CONFIG_COPY).write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    checker = scripts / "check_docs.py"
    if status[LEVELS_PATH] in ("新建", "替换"):
        subprocess.run([sys.executable, str(checker), str(target), "--init", "--force"],
                       check=True, stdout=subprocess.DEVNULL)

    print("已写入。检查结果：", flush=True)
    return subprocess.run([sys.executable, str(checker), str(target)]).returncode


def main():
    parser = argparse.ArgumentParser(description="按渲染配置生成协作规范")
    parser.add_argument("config", help="渲染配置 JSON 文件")
    parser.add_argument("target", help="目标项目根目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="列出将生成的文件，不写入")
    mode.add_argument("--print", dest="print_path", metavar="路径", help="输出单个生成文件的内容，不写入")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"目标目录不存在：{target}")
        return 2

    try:
        cfg = load_config(Path(args.config))
        check_paths(cfg, target)
        conds = conditions(cfg)
        rendered = render_all(cfg, conds)
    except ConfigError as exc:
        print(exc)
        return 1

    if args.print_path:
        if args.print_path not in rendered:
            print(f"不是生成文件：{args.print_path}。用 --plan 查看生成清单。")
            return 2
        sys.stdout.write(rendered[args.print_path])
        return 0

    status = statuses(cfg, target, list(rendered) + other_outputs())
    if print_plan(rendered, status) or args.plan:
        return 1 if any(s == "冲突" for s in status.values()) else 0

    print()
    return write_all(cfg, target, rendered, status)


if __name__ == "__main__":
    sys.exit(main())

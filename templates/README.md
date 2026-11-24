# 生成模板

`scripts/render.py` 按渲染配置渲染本目录的模板。模板中的文字是生成结果的正文；占位符和条件块在生成时替换或删除，不得残留在目标项目中，残留由 `render.py` 和 `check_docs.py` 报错。

## 渲染配置

JSON 对象。字符串中的 `@@路径@@`（相对目标项目根目录）在每个生成文件中换算为相对于该文件的路径；这些路径必须在目标项目中存在。

| 字段 | 必填 | 内容 |
| --- | --- | --- |
| `project` | 是 | 项目短名，小写字母、数字和连字符，用于 skill 名称 |
| `tier` | 是 | `轻量`、`标准` 或 `严格`，定义见 [tiers.md](../tiers.md) |
| `gate` | 否 | 用户 review 的时机；省略时按档位取默认值 |
| `style_review` | 否 | 风格审查模式：`建议` 或 `必改`，定义见 [tiers.md](../tiers.md)；省略时轻量档为建议，标准档、严格档为必改 |
| `style_review_tests` | 否 | 风格检查是否包括测试代码，`true` 或 `false`；省略时为 `true` |
| `languages` | 是 | 主语言数组，见下表 |
| `contract_docs` | 否 | 业务契约文档数组，每项 `{name, path, scope}`；`path` 相对项目根目录 |
| `high_risk_areas` | 否 | 高风险区域数组，每项 `{area, code, invariants, source}` |
| `domain_checks` | 否 | 领域审查要点数组，每项 `{capability, checks, source}` |
| `migration` | 否 | 迁移项目时填写 `{plan, test_cmd}`：`plan` 是迁移规划的说明与链接，`test_cmd` 是运行旧实现测试的命令 |
| `existing_collab` | 否 | 已有协作文件的处理说明，每项一行 Markdown |
| `tools` | 否 | 生成子 agent 定义的工具数组，取值 `claude`、`codex`；省略时只生成工具无关的规范 |
| `models` | 否 | 按工具和角色指定模型，如 `{"claude": {"architect": "fable", "coder": "opus", "reviewer": "opus"}}`；角色为 `architect`、`coder`、`reviewer`，未填写的角色继承主会话模型。模型名写该工具接受的值，生成器不校验是否存在 |
| `replace`、`skip` | 否 | 目标项目中已存在、要替换或保留的生成路径；未声明的已存在文件视为冲突 |

`languages` 每项：

| 字段 | 必填 | 内容 |
| --- | --- | --- |
| `name`、`id` | 是 | 语言名称（如 Go）与目录名（小写，如 go） |
| `dirs` | 是 | 该语言代码所在目录数组 |
| `format_cmd`、`lint_cmd`、`test_cmd`、`build_cmd` | 否 | 命令；省略时写“待确认” |
| `style_tools` | 否 | 格式化与 lint 工具及配置文件说明（Markdown） |
| `style_rules` 或 `style_rules_file` | 是 | 文字风格规则，每条一个三级标题小节：说明、来源、好的写法、不好的写法；`style_rules_file` 相对配置文件所在目录 |
| `plan_routes` | 否 | 该语言相关的规划文档路由，每项 `{label, title, path}` |

表格单元格字段（高风险区域、领域要点各字段）不能包含 `|` 或换行。

## 占位符

| 占位符 | 来源 |
| --- | --- |
| `{{PROJECT}}` `{{TIER}}` `{{GATE}}` | 同名配置字段 |
| `{{BLOCKING_LEVELS}}` | 轻量档且风格审查模式为建议时 P0、P1；其余为 P0、P1、P2 |
| `{{STYLE_SCOPE}}` | 按 `style_review_tests`：风格检查的差异范围是否包括测试代码。只在 `topics/review-severity.md` 中使用，其他模板引用该专题 |
| `{{LANG}}` `{{LANG_ID}}` `{{LANG_DIRS}}` | 当前语言的 `name`、`id`、`dirs` |
| `{{FORMAT_CMD}}` `{{LINT_CMD}}` `{{TEST_CMD}}` `{{BUILD_CMD}}` | 当前语言的命令字段 |
| `{{STYLE_TOOLS}}` `{{STYLE_RULES}}` | 当前语言的 `style_tools`、`style_rules` |
| `{{PLAN_ROUTES}}` | 当前语言的 `plan_routes`，每项一行路由；没有时连同所在行删除 |
| `{{LANG_ROUTES}}` | 每种语言一行，指向其语言入口 |
| `{{LANG_INDEX_ROUTES}}` | 每种语言一行，指向其编码索引 |
| `{{CONTRACT_DOCS}}` | `contract_docs`，每项一行 `- [名称](路径)：范围` |
| `{{HIGH_RISK_AREAS}}` `{{DOMAIN_CHECKS}}` | 对应数组，每项一行表格 |
| `{{MIGRATION_PLAN}}` `{{MIGRATION_TEST_CMD}}` | `migration` 的 `plan`、`test_cmd` |
| `{{EXISTING_COLLAB}}` | `existing_collab`，每项一行 |
| `{{CLAUDE_ARCHITECT_MODEL}}` `{{CODEX_ARCHITECT_MODEL}}` | `models.<工具>.architect`，未填写时为“继承” |
| `{{CLAUDE_AGENT_ROWS}}` `{{CODEX_AGENT_ROWS}}` | 该工具的子 agent 表，每个 agent 一行：名称、角色、模型 |
| `{{AGENT_NAME}}` `{{AGENT_NAME_TOML}}` `{{AGENT_DESCRIPTION}}` `{{AGENT_MODEL_LINE}}` `{{AGENT_TOOLS_LINE}}` `{{AGENT_SKILL_LINK}}` `{{AGENT_SKILL_PATH}}` | 只用于 `tools/` 下的 agent 定义模板，由 `render.py` 的 `agent_values` 按每个 agent 生成；描述取对应 skill 的 `description` |

模板中出现没有值的占位符时，`render.py` 报错并停止，不写入任何文件。新增占位符时，同时修改 `render.py` 的 `values` 函数和本表。

## 条件块

`<!-- 条件: X -->` 与 `<!-- /条件 -->` 各占一行，之间的内容只在条件成立时保留；生成时删除标记所在的整行。条件块不嵌套。多个条件用逗号分隔，任一成立即保留；档位可简写，如 `档位=标准,严格`。

表格中间不能出现空行，否则表格在空行处断开，后面的行不再被识别为路由。替换为空的占位符连同所在行一起删除。`check_docs.py` 会报告被空行断开的路由表。

条件由配置自动推导：

| 条件 | 成立情况 |
| --- | --- |
| `档位=轻量`、`档位=标准`、`档位=严格` | `tier` 相符 |
| `有高风险区域` | `high_risk_areas` 非空 |
| `有领域要点` | `domain_checks` 非空 |
| `轻量升档` | 档位为轻量且有高风险区域 |
| `升档提高阻断` | 轻量档、有高风险区域且风格审查模式为建议：升档后的阻断级别比平时多出 P2 |
| `迁移项目` | 填写了 `migration` |
| `单语言`、`多语言` | `languages` 为一种，或两种及以上 |
| `有已有协作文件` | `existing_collab` 非空 |
| `使用Claude`、`使用Codex` | `tools` 包含 `claude`、`codex` |
| `风格建议`、`风格必改` | `style_review` 相符 |
| `代码审查风格建议`、`代码审查风格必改` | 档位不是严格档，且 `style_review` 相符；严格档由风格审查职能核对风格 |

## 默认目录与生成条件

由 `render.py` 的 `plan_files` 函数实现；修改生成规则时两处同步。

| 模板 | 生成位置 | 生成条件 |
| --- | --- | --- |
| `root-entry.md` | `AGENTS.md`（L0） | 总是 |
| `lang-entry.md` | `.agents/<语言 id>/entry.md`（L1） | 多语言时每种语言一份；单语言时不生成，路由并入 L0 |
| `coding-index.md` | `.agents/<语言 id>/coding-index.md`（L2） | 每种语言一份 |
| `topics/style.md`、`topics/toolchain.md` | `.agents/<语言 id>/` 下同名（L3，语言专用） | 每种语言一份 |
| `topics/` 中其余专题 | `.agents/references/` 下同名（L3，各语言共用） | 总是；以下除外：`high-risk-areas.md` 仅在有高风险区域时生成，`domain-checks.md` 仅在有领域要点时生成，`migration-comparison.md` 仅在迁移项目时生成 |
| `roles/coder.md` | `.agents/skills/<project>-coder/SKILL.md` | 总是 |
| `review/single-reviewer.md` | `.agents/skills/<project>-review/SKILL.md` | 档位=轻量 |
| `review/coordinator.md` | `.agents/skills/<project>-review-coordinator/SKILL.md` | 档位=标准、严格，或轻量升档 |
| `review/code-review.md` | `.agents/skills/<project>-code-review/SKILL.md` | 总是 |
| `review/behavior-verification.md` | `.agents/skills/<project>-behavior-verification/SKILL.md` | 总是 |
| `review/style-review.md` | `.agents/skills/<project>-style-review/SKILL.md` | 档位=严格 |
| `decisions/README.md`、`decisions/_template.md` | `.agents/decisions/` 下同名 | 总是 |
| `agent-record/README.md`、`agent-record/_template.md`、`agent-record/_contract-template.md`、`agent-record/_autonomous-template.md` | `.agents/agentRecord/` 下同名 | 总是 |
| `tools/CLAUDE.md` | `CLAUDE.md`，导入 `AGENTS.md` | `tools` 包含 `claude` |
| `tools/claude-agent.md` | `.claude/agents/<project>-<职能>.md`，Coder 与各审查职能各一份（不含协调者） | `tools` 包含 `claude` |
| `tools/codex-agent.toml` | `.codex/agents/<project>-<职能>.toml`，同上 | `tools` 包含 `codex` |
| `../scripts/snapshot.sh`、`../scripts/check_docs.py` | `.agents/scripts/` 下同名，原样复制 | 总是 |
| 层级映射 `levels.json` | `.agents/scripts/levels.json`，由 `check_docs.py --init` 生成 | 总是 |
| 配置副本 | `.agents/scripts/workflow-config.json`，去掉 `replace`、`skip`，风格规则内联 | 总是 |

skill 文件通过 L0 的路由读取，不依赖工具的自动发现机制。配置了 `tools` 时，生成器为该工具生成子 agent 定义，用于指定模型和工具权限；定义只是薄包装，执行内容指向对应 skill，规则正文只在 skill 中维护一份。审查协调者由主会话担任，不生成 agent 定义。

`.agents/decisions/` 中的 ADR、`.agents/agentRecord/` 中的任务记录与契约不是规范文件，`check_docs.py` 不把它们计入层级映射；两处的 README 是规范文件。

轻量档总是生成代码审查与行为验证两个 skill：单个审查者依次执行它们，升档时协调者直接分派它们，检查内容只维护一份。

`agent-record/_contract-template.md` 第 7 节预填了 `root-entry.md` 中角色、推进门禁和提交三处的原文，供每份契约直接引用。修改 `root-entry.md` 的这三处时，同步修改契约模板。

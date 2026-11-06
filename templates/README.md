# 生成模板

`scripts/render.py` 按渲染配置渲染本目录的模板。模板中的文字是生成结果的正文；占位符和条件块在生成时替换或删除，不得残留在目标项目中，残留由 `render.py` 和 `check_docs.py` 报错。

## 渲染配置

JSON 对象。字符串中的 `@@路径@@`（相对目标项目根目录）在每个生成文件中换算为相对于该文件的路径；这些路径必须在目标项目中存在。

| 字段 | 必填 | 内容 |
| --- | --- | --- |
| `project` | 是 | 项目短名，小写字母、数字和连字符，用于 skill 名称 |
| `tier` | 是 | `轻量`、`标准` 或 `严格`，定义见 [tiers.md](../tiers.md) |
| `gate` | 否 | 用户 review 的时机；省略时按档位取默认值 |
| `languages` | 是 | 主语言数组，见下表 |
| `contract_docs` | 否 | 业务契约文档数组，每项 `{name, path, scope}`；`path` 相对项目根目录 |
| `high_risk_areas` | 否 | 高风险区域数组，每项 `{area, code, invariants, source}` |
| `domain_checks` | 否 | 领域审查要点数组，每项 `{capability, checks, source}` |
| `migration` | 否 | 迁移项目时填写 `{plan, test_cmd}`：`plan` 是迁移规划的说明与链接，`test_cmd` 是运行旧实现测试的命令 |
| `existing_collab` | 否 | 已有协作文件的处理说明，每项一行 Markdown |
| `replace`、`skip` | 否 | 目标项目中已存在、要替换或保留的生成路径；未声明的已存在文件视为冲突 |

`languages` 每项：

| 字段 | 必填 | 内容 |
| --- | --- | --- |
| `name`、`id` | 是 | 语言名称（如 Go）与目录名（小写，如 go） |
| `dirs` | 是 | 该语言代码所在目录数组 |
| `format_cmd`、`lint_cmd`、`test_cmd`、`build_cmd` | 否 | 命令；省略时写“待确认” |
| `style_tools` | 否 | 格式化与 lint 工具及配置文件说明（Markdown） |
| `style_rules` 或 `style_rules_file` | 标准档、严格档必填 | 文字风格规则，每条一个三级标题小节：说明、来源、好的写法、不好的写法；`style_rules_file` 相对配置文件所在目录 |
| `plan_routes` | 否 | 该语言相关的规划文档路由，每项 `{label, title, path}` |

表格单元格字段（高风险区域、领域要点各字段）不能包含 `|` 或换行。

## 占位符

| 占位符 | 来源 |
| --- | --- |
| `{{PROJECT}}` `{{TIER}}` `{{GATE}}` | 同名配置字段 |
| `{{BLOCKING_LEVELS}}` | 按档位：轻量 P0、P1；标准、严格 P0、P1、P2 |
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
| `迁移项目` | 填写了 `migration` |
| `单语言`、`多语言` | `languages` 为一种，或两种及以上 |
| `有已有协作文件` | `existing_collab` 非空 |

## 默认目录与生成条件

由 `render.py` 的 `plan_files` 函数实现；修改生成规则时两处同步。

| 模板 | 生成位置 | 生成条件 |
| --- | --- | --- |
| `root-entry.md` | `AGENTS.md`（L0） | 总是 |
| `lang-entry.md` | `.agents/<语言 id>/entry.md`（L1） | 多语言时每种语言一份；单语言时不生成，路由并入 L0 |
| `coding-index.md` | `.agents/<语言 id>/coding-index.md`（L2） | 每种语言一份 |
| `topics/style.md`、`topics/toolchain.md` | `.agents/<语言 id>/` 下同名（L3，语言专用） | 每种语言一份 |
| `topics/` 中其余专题 | `.agents/references/` 下同名（L3，各语言共用） | 总是；以下除外：`high-risk-areas.md` 仅在有高风险区域时生成，`domain-checks.md` 仅在有领域要点时生成，`migration-comparison.md` 仅在迁移项目时生成 |
| `review/single-reviewer.md` | `.agents/skills/<project>-review/SKILL.md` | 档位=轻量 |
| `review/coordinator.md` | `.agents/skills/<project>-review-coordinator/SKILL.md` | 档位=标准、严格，或轻量升档 |
| `review/code-review.md` | `.agents/skills/<project>-code-review/SKILL.md` | 总是 |
| `review/behavior-verification.md` | `.agents/skills/<project>-behavior-verification/SKILL.md` | 总是 |
| `review/style-review.md` | `.agents/skills/<project>-style-review/SKILL.md` | 档位=严格 |
| `agent-record/README.md`、`agent-record/_template.md` | `.agents/agentRecord/` 下同名 | 总是 |
| `../scripts/snapshot.sh`、`../scripts/check_docs.py` | `.agents/scripts/` 下同名，原样复制 | 总是 |
| 层级映射 `levels.json` | `.agents/scripts/levels.json`，由 `check_docs.py --init` 生成 | 总是 |
| 配置副本 | `.agents/scripts/workflow-config.json`，去掉 `replace`、`skip`，风格规则内联 | 总是 |

skill 文件通过 L0 的路由读取，不依赖工具的自动发现机制。用户需要某个工具自动加载时，可在交付后另行建立链接，生成器不为特定工具生成目录。

轻量档总是生成代码审查与行为验证两个 skill：单个审查者依次执行它们，升档时协调者直接分派它们，检查内容只维护一份。

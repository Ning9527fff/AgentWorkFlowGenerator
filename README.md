# agent-workflow-generator

为目标项目生成 agent 协作工作流的 skill，入口见 [SKILL.md](SKILL.md)。

协作模式参考 dsh agent 规范实现，并加入了档位划分、严重度阈值和单层分派等调整。

## 文件

| 文件 | 内容 |
| --- | --- |
| [SKILL.md](SKILL.md) | 生成器主流程 |
| [tiers.md](tiers.md) | 档位、自动升档、分派方式与严重度 |
| [index-structure.md](index-structure.md) | 生成规范的多级索引结构、链接分类与读取规则 |
| [style-sourcing.md](style-sourcing.md) | 按项目主语言确定代码风格规范的方法 |
| [simulation-check.md](simulation-check.md) | 交付前的模拟任务检查 |
| [templates/](templates/README.md) | 生成模板：入口、编码索引、专题、审查 skill、任务记录；占位符与条件块规则 |
| `scripts/render.py` | 按渲染配置生成规范：`--plan` 列清单，`--print` 输出单个文件，默认写入并运行检查 |
| `scripts/snapshot.sh` | 生成审查快照：基线提交加改动文件逐文件摘要（不含任务记录目录） |
| `scripts/check_docs.py` | 检查生成的规范：链接、模板残留、路由单向无环、可达性；维护层级映射 `levels.json`（`--init`、`--set`、`--update`） |

脚本依赖 git、bash 和 Python 3.9 及以上，不需要第三方包。`snapshot.sh` 与 `check_docs.py` 会复制到目标项目，`render.py` 只在生成时使用。

## 许可

本项目以 [MIT 协议](LICENSE) 发布。

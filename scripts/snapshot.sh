#!/usr/bin/env bash
# 生成审查快照：基线提交 + 相对基线的已提交、已暂存、未暂存改动及未跟踪文件的逐文件摘要。
# 用法：bash snapshot.sh [基线提交，默认 HEAD]
# 输出：逐文件清单（状态、SHA256、路径），最后一行为整体摘要。同一代码状态多次运行结果相同。
# 覆盖整个仓库，不提供路径过滤，保证各方对同一状态得到同一摘要。
# 任务记录目录 .agents/agentRecord/ 不计入快照：审查期间写入台账不改变摘要。
set -euo pipefail

if [ "$#" -gt 1 ]; then
  echo "用法：bash snapshot.sh [基线提交]（不支持路径过滤）" >&2
  exit 2
fi

base="${1:-HEAD}"
record_dir=".agents/agentRecord"

root="$(git rev-parse --show-toplevel)"
cd "$root"

base_commit="$(git rev-parse --verify "${base}^{commit}")"

# 相对基线变化的文件（含已提交、已暂存和未暂存），加上未跟踪且未被忽略的文件。
changed="$(
  {
    git -c core.quotePath=false diff --name-only "$base_commit" -- . ":(exclude)${record_dir}"
    git -c core.quotePath=false ls-files --others --exclude-standard -- . ":(exclude)${record_dir}"
  } | LC_ALL=C sort -u
)"

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

hash_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  else
    shasum -a 256 | cut -d' ' -f1
  fi
}

manifest="base ${base_commit}"
count=0
while IFS= read -r path; do
  [ -z "$path" ] && continue
  if [ -f "$path" ]; then
    entry="present $(hash_file "$path") ${path}"
  else
    entry="deleted - ${path}"
  fi
  manifest="${manifest}"$'\n'"${entry}"
  count=$((count + 1))
done <<< "$changed"

printf '%s\n' "$manifest"
printf 'files %d\n' "$count"
printf 'snapshot %s\n' "$(printf '%s\n' "$manifest" | hash_stdin)"

#!/usr/bin/env bash
#
# rename_for_submission.sh · 把作品目录改成官方要求的提交命名
#
# 官方要求目录位于：submissions/mcp-hackathon/<team-or-builder>-<project-slug>/
# 本作品的提交名应为：<你的GitHub用户名>-api-mcp-toolkit
#
# 用法：
#   bash tools/rename_for_submission.sh <你的GitHub用户名>
#
# 默认先做演练（只打印将要执行的操作）。确认无误后加 --apply 真正执行：
#   bash tools/rename_for_submission.sh <用户名> --apply
#
set -euo pipefail

USERNAME="${1:-}"
MODE="${2:-}"

if [[ -z "$USERNAME" ]]; then
  echo "用法：bash tools/rename_for_submission.sh <你的GitHub用户名> [--apply]" >&2
  echo "例如：bash tools/rename_for_submission.sh octocat --apply" >&2
  exit 2
fi

# GitHub 用户名规则：字母数字与连字符，不能以连字符开头/结尾，最长 39
if [[ ! "$USERNAME" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?$ ]]; then
  echo "错误：'$USERNAME' 不是合法的 GitHub 用户名（仅字母数字与连字符，且不能以连字符开头或结尾）" >&2
  exit 2
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$PROJECT_DIR")"
TARGET_NAME="${USERNAME}-api-mcp-toolkit"
TARGET_DIR="${PARENT}/${TARGET_NAME}"

echo "作品目录     : $PROJECT_DIR"
echo "目标目录     : $TARGET_DIR"
echo

if [[ "$PROJECT_DIR" == "$TARGET_DIR" ]]; then
  echo "目录名已经是 ${TARGET_NAME}，无需改名。"
  exit 0
fi

if [[ -e "$TARGET_DIR" ]]; then
  echo "错误：目标目录已存在，请先处理：$TARGET_DIR" >&2
  exit 1
fi

if [[ "$MODE" != "--apply" ]]; then
  echo "[演练模式] 将要执行："
  echo "  mv \"$PROJECT_DIR\" \"$TARGET_DIR\""
  echo
  echo "确认后请重新执行并加上 --apply"
  exit 0
fi

mv "$PROJECT_DIR" "$TARGET_DIR"
echo "已改名 -> $TARGET_DIR"
echo
echo "后续步骤："
echo "  1) cd \"$TARGET_DIR\""
echo "  2) Fork https://github.com/xagentAI/xagt-plugin 并 clone 到本地"
echo "  3) 把本目录整体复制到 <fork>/submissions/mcp-hackathon/${TARGET_NAME}/"
echo "  4) git add -A && git add -f verification-evidence.md docs/ && git commit -m \"feat: ${TARGET_NAME} · Open Innovation\""
echo "  5) push 后在官方仓库开 PR（标题含项目名 + Open Innovation）"

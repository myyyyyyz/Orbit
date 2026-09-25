#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 把开发分支同步为「干净的上线分支」
#
#   master 的内容 = dev/optimize 的代码 − RELEASE_EXCLUDES
#
# 设计要点：
#   1. 排除清单集中在本文件底部，唯一事实源，不再手工挑文件；
#   2. 每次同步在 master 上生成**一个** release 提交，
#      master 历史只有发版记录，不掺入开发分支的中间提交；
#   3. 只做快进 + 追加提交，绝不改写 master 已有历史；
#   4. 同步后自动校验「master 相对 dev 的差异恰好等于排除清单」。
#
# 用法：
#   bash scripts/sync-master.sh          # 生成 release 提交（本地）
#   bash scripts/sync-master.sh --push   # 生成并推送两个分支
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DEV_BRANCH="${DEV_BRANCH:-dev/optimize}"
REL_BRANCH="${REL_BRANCH:-master}"
PUSH=0
[ "${1:-}" = "--push" ] && PUSH=1

die() { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }
info() { printf '\033[36m▸ %s\033[0m\n' "$1"; }
ok() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

cd "$(git rev-parse --show-toplevel)"

# ── 0. 前置检查 ──────────────────────────────────────────────
git rev-parse --verify --quiet "refs/heads/$DEV_BRANCH" >/dev/null \
  || die "本地不存在分支 $DEV_BRANCH"
git rev-parse --verify --quiet "refs/heads/$REL_BRANCH" >/dev/null \
  || die "本地不存在分支 $REL_BRANCH"
git diff --quiet || die "工作区有未提交改动，先 commit 或 stash"
git diff --cached --quiet || die "暂存区有未提交改动，先 commit 或 stash"

info "拉取远端..."
git fetch origin --quiet || die "git fetch 失败"

git checkout "$REL_BRANCH" --quiet
git merge --ff-only "origin/$REL_BRANCH" --quiet 2>/dev/null \
  || die "本地 $REL_BRANCH 与 origin/$REL_BRANCH 已分叉，请先手工处理"

BEFORE_HEAD="$(git rev-parse HEAD)"
DEV_SHA="$(git rev-parse --short "$DEV_BRANCH")"
info "$REL_BRANCH 基线 $BEFORE_HEAD ／ $DEV_BRANCH 源 $DEV_SHA"

# ── 1. 计算排除清单 ──────────────────────────────────────────
# 1a. 固定清单（目录 / 文件）
EXCLUDES=(
  "docs"                       # 全部开发文档（设计/计划/体检报告/部署记录）
  "backend/test"               # 后端 pytest 套件
  "frontend/test"              # 前端独立测试目录
  "frontend/src/test"          # 前端测试工具目录
  "frontend/vitest.config.ts"  # 前端测试配置
  "frontend/vitest.config.mts"
  ".playwright-cli"            # 本地浏览器自动化产物
  "login.yaml"                 # 本地调试用登录探针
  "main.png"
  "ui-01-initial.png"
  "中小微企业+个人agent方案.md"
  "产品用户缺点评估与扩展建议.md"
  "项目落地计划.md"
  "scripts/sync-master.sh"     # 本脚本自身：开发工具，不上线
)

# 1b. 前端散落的 *.test.ts(x) —— 目录约定之外，按模式补扫
while IFS= read -r path; do
  [ -n "$path" ] && EXCLUDES+=("$path")
done < <(
  git ls-tree -r --name-only "$DEV_BRANCH" -- frontend \
    | grep -E '\.(test|spec)\.(ts|tsx|js|jsx)$' || true
)

# ── 2. 用 dev 分支的文件树整体覆盖，再剔除排除项 ────────────
info "以 $DEV_BRANCH 的文件树重建 $REL_BRANCH 内容..."
git read-tree --reset -u "$DEV_BRANCH"

REMOVED=0
for path in "${EXCLUDES[@]}"; do
  if git rm -r -q --ignore-unmatch -- "$path" >/dev/null 2>&1; then
    REMOVED=$((REMOVED + 1))
  fi
done
ok "已剔除 $REMOVED 个排除项"

# ── 3. 生成 release 提交 ─────────────────────────────────────
if git diff --cached --quiet; then
  ok "$REL_BRANCH 已与 $DEV_BRANCH 一致（排除项之外无变化），无需提交"
else
  git commit -q -m "release: 同步 $DEV_BRANCH@$DEV_SHA

由 scripts/sync-master.sh 生成：内容 = $DEV_BRANCH 代码 − 开发文档与测试脚本。"
  ok "release 提交 $(git rev-parse --short HEAD)"
fi

# ── 4. 校验：master 与 dev 的差异必须恰好等于排除清单 ────────
info "校验差异..."
LEAK="$(git diff --name-only "$REL_BRANCH" "$DEV_BRANCH" | while IFS= read -r f; do
  keep=1
  for path in "${EXCLUDES[@]}"; do
    case "$f" in
      "$path"|"$path"/*) keep=0; break ;;
    esac
  done
  [ "$keep" = 1 ] && printf '%s\n' "$f"
done)"

if [ -n "$LEAK" ]; then
  printf '%s\n' "$LEAK" | head -30 >&2
  die "有非排除项的文件差异（上面列出），请检查排除清单"
fi
ok "差异校验通过：$REL_BRANCH 相对 $DEV_BRANCH 仅少了排除项"

# ── 5. 推送 ──────────────────────────────────────────────────
if [ "$PUSH" = 1 ]; then
  git push origin "$DEV_BRANCH"
  git push origin "$REL_BRANCH"
  ok "已推送 $DEV_BRANCH 与 $REL_BRANCH"
else
  info "未推送（加 --push 可推送两分支）"
fi

git checkout "$DEV_BRANCH" --quiet
ok "完成，已切回 $DEV_BRANCH"

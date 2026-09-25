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
#   4. 提交前先校验「暂存内容相对 dev 的差异恰好等于排除清单」，
#      任何非排除项漏进 master 都会直接中止；
#   5. 幂等：重复执行且 dev 无新提交时不会产生空提交。
#
# 用法：
#   bash scripts/sync-master.sh          # 生成 release 提交（本地）
#   bash scripts/sync-master.sh --push   # 生成并推送两个分支
#
# 注意：脚本面向 macOS 自带 bash 3.2，不使用 mapfile / 关联数组 / case-in-$()。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DEV_BRANCH="${DEV_BRANCH:-dev/optimize}"
REL_BRANCH="${REL_BRANCH:-master}"
PUSH=0
[ "${1:-}" = "--push" ] && PUSH=1

die() { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }
info() { printf '\033[36m▸ %s\033[0m\n' "$1"; }
warn() { printf '\033[33m! %s\033[0m\n' "$1"; }
ok() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

cd "$(git rev-parse --show-toplevel)"

# ── 排除清单：上线分支要剔除的开发资产 ──────────────────────
RELEASE_EXCLUDES=(
  "docs"                        # 全部开发文档（设计/计划/体检报告/部署记录）
  "backend/test"                # 后端 pytest 套件
  "frontend/test"               # 前端独立测试目录
  "frontend/src/test"           # 前端测试工具目录
  "frontend/vitest.config.ts"   # 前端测试配置
  "frontend/vitest.config.mts"
  ".playwright-cli"             # 本地浏览器自动化产物
  "login.yaml"                  # 本地调试用登录探针
  "main.png"
  "ui-01-initial.png"
  "中小微企业+个人agent方案.md"
  "产品用户缺点评估与扩展建议.md"
  "项目落地计划.md"
  "scripts/sync-master.sh"      # 本脚本自身：开发工具，不上线
)

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
if ! git merge --ff-only "origin/$REL_BRANCH" --quiet 2>/dev/null; then
  die "本地 $REL_BRANCH 与 origin/$REL_BRANCH 已分叉，请先手工处理"
fi

DEV_SHA="$(git rev-parse --short "$DEV_BRANCH")"
info "$REL_BRANCH 基线 $(git rev-parse --short HEAD) ／ $DEV_BRANCH 源 $DEV_SHA"

# ── 1. 补扫散落的测试文件（目录约定之外） ────────────────────
while IFS= read -r path; do
  [ -n "$path" ] && RELEASE_EXCLUDES+=("$path")
done < <(
  git -c core.quotepath=false ls-tree -r --name-only "$DEV_BRANCH" -- frontend \
    | grep -E '\.(test|spec)\.(ts|tsx|js|jsx)$' || true
)

# ── 1b. 归一化：丢弃已被更上层条目覆盖的冗余路径 ────────────
NORMALIZED=()
i=0
while [ "$i" -lt "${#RELEASE_EXCLUDES[@]}" ]; do
  p="${RELEASE_EXCLUDES[$i]}"
  covered=0
  j=0
  while [ "$j" -lt "${#RELEASE_EXCLUDES[@]}" ]; do
    q="${RELEASE_EXCLUDES[$j]}"
    if [ "$p" != "$q" ] && [ "${p#"$q"/}" != "$p" ]; then
      covered=1
      break
    fi
    j=$((j + 1))
  done
  if [ "$covered" = 0 ]; then
    NORMALIZED+=("$p")
  fi
  i=$((i + 1))
done
RELEASE_EXCLUDES=("${NORMALIZED[@]}")

# ── 1c. 区分「确实存在」与「清单里写多余了」的条目 ──────────
PRESENT=()
MISSING=""
for path in "${RELEASE_EXCLUDES[@]}"; do
  if [ -n "$(git -c core.quotepath=false ls-tree -r --name-only "$DEV_BRANCH" -- "$path")" ]; then
    PRESENT+=("$path")
  else
    MISSING="$MISSING  $path"
  fi
done
if [ -n "$MISSING" ]; then
  warn "以下排除项在 $DEV_BRANCH 中不存在，可从清单移除:$MISSING"
fi

# ── 2. 用 dev 分支的文件树整体覆盖，再逐个剔除排除项 ────────
info "以 $DEV_BRANCH 的文件树重建 $REL_BRANCH 内容..."
git read-tree --reset -u "$DEV_BRANCH"

for path in "${PRESENT[@]}"; do
  # -f 必需：此时索引内容与 HEAD 不一致，git rm 默认会拒绝执行
  git rm -r -q -f --ignore-unmatch -- "$path" || die "剔除 $path 失败"
done
ok "已剔除 ${#PRESENT[@]} 项"

# ── 3. 提交前校验：与 dev 的差异必须恰好是排除清单 ──────────
EXFILE="$(mktemp)"
printf '%s\n' "${RELEASE_EXCLUDES[@]}" > "$EXFILE"
LEAK="$(git -c core.quotepath=false diff --name-only --cached "$DEV_BRANCH" | awk '
  NR == FNR { excl[++n] = $0; next }
  {
    keep = 1
    for (i = 1; i <= n; i++) {
      p = excl[i]
      if ($0 == p || index($0, p "/") == 1) { keep = 0; break }
    }
    if (keep) print
  }
' "$EXFILE" -)"
rm -f "$EXFILE"

if [ -n "$LEAK" ]; then
  printf '%s\n' "$LEAK" | head -30 >&2
  die "以上文件不在排除清单内却未同步到 $REL_BRANCH，请检查 RELEASE_EXCLUDES"
fi
ok "校验通过：相对 $DEV_BRANCH 的差异仅为排除项"

# ── 4. 生成 release 提交 ─────────────────────────────────────
if git diff --cached --quiet; then
  ok "$REL_BRANCH 已与 $DEV_BRANCH 一致（排除项之外无变化），无需提交"
else
  git commit -q -m "release: 同步 $DEV_BRANCH@$DEV_SHA

由 scripts/sync-master.sh 生成：内容 = $DEV_BRANCH 代码 − 开发文档与测试脚本。"
  ok "release 提交 $(git rev-parse --short HEAD)"
fi

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

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 上线分支（master）的唯一同步入口
#
#   master 的内容 = dev/optimize 的代码 − RELEASE_EXCLUDES
#
# 铁律：**master 不得手工编辑，也不得直接 push**。
#   正确流程（见 docs/RELEASE-PROCESS.md）：
#     1. 在 dev/optimize 上开发、提交、push  → CI 自动跑
#     2. 本脚本生成 release 分支并发起 PR     → CI 再跑一遍 + 人工 review
#     3. 流水线全绿且 review 通过后合入 master
#
# 三种模式：
#   （默认）        生成 release/sync-<devsha> 分支并推送，打印 PR 链接
#   --verify <ref>  只读校验：<ref> 的树必须恰好等于「dev − 排除清单」
#                   （CI 的 release-sync job 用它，不做任何写操作）
#   --direct        应急直推 master，绕过 review 与门禁。仅在线上回滚等
#                   紧急场景使用，需二次确认。
#
# 说明：脚本面向 macOS 自带 bash 3.2，不使用 mapfile / 关联数组。
# ⚠️ 本脚本含中文提示语，务必写 ${VAR} 而不是 $VAR：
#    bash 3.2 会把紧跟变量名的多字节字符首字节并进变量名，报
#    "VAR<乱码>: unbound variable"，而且是在失败分支上才炸——很容易漏掉。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DEV_BRANCH="${DEV_BRANCH:-dev/optimize}"
REL_BRANCH="${REL_BRANCH:-master}"

MODE="pr"
VERIFY_REF=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--verify" ]; then
    MODE="verify"
    VERIFY_REF="${2:-}"
    if [ -z "$VERIFY_REF" ]; then
      printf '✗ --verify 需要一个 ref\n' >&2
      exit 2
    fi
    shift 2
  elif [ "$1" = "--direct" ]; then
    MODE="direct"
    shift
  elif [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    sed -n '2,20p' "$0"
    exit 0
  else
    printf '✗ 未知参数：%s（可用：--verify <ref> / --direct / --help）\n' "$1" >&2
    exit 2
  fi
done

die() { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }
info() { printf '\033[36m▸ %s\033[0m\n' "$1"; }
warn() { printf '\033[33m! %s\033[0m\n' "$1"; }
ok() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

cd "$(git rev-parse --show-toplevel)"

# ── 排除清单：上线分支必须剔除的开发资产（唯一事实源）────────
STATIC_EXCLUDES=(
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
RELEASE_EXCLUDES=()

build_excludes() {
  local ref="${1:-$DEV_BRANCH}"
  RELEASE_EXCLUDES=("${STATIC_EXCLUDES[@]}")

  # 目录约定之外散落的测试文件，按模式补扫
  local path
  while IFS= read -r path; do
    if [ -n "$path" ]; then
      RELEASE_EXCLUDES+=("$path")
    fi
  done < <(
    git -c core.quotepath=false ls-tree -r --name-only "$ref" -- frontend \
      | grep -E '\.(test|spec)\.(ts|tsx|js|jsx)$' || true
  )

  # 归一化：丢弃已被更上层条目覆盖的冗余路径
  local NORMALIZED=() p q covered i j
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
}

# 路径 $1 是否命中排除清单（含目录前缀匹配）
is_excluded() {
  local f="$1" p
  for p in "${RELEASE_EXCLUDES[@]}"; do
    if [ "$f" = "$p" ] || [ "${f#"$p"/}" != "$f" ]; then
      return 0
    fi
  done
  return 1
}

# ── 模式：--verify（只读，供 CI 使用）────────────────────────
cmd_verify() {
  git rev-parse --verify --quiet "$VERIFY_REF" >/dev/null \
    || die "看不到 ref：$VERIFY_REF"
  git rev-parse --verify --quiet "refs/heads/$DEV_BRANCH" >/dev/null \
    || die "本地不存在分支 $DEV_BRANCH"

  # 比较基准取「release 提交里记录的那个 dev 版本」，而不是 dev 的当前 tip：
  # 否则只要 dev 又推进了提交，已经开着的发版 PR 就会被误判为红。
  local BASE
  BASE="$(git log -1 --format=%s "$VERIFY_REF" \
    | sed -n 's/.*dev\/optimize@\([0-9a-f][0-9a-f]*\)$/\1/p')"
  if [ -n "$BASE" ] && git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null; then
    info "比较基准：release 提交声明的 dev/optimize@$BASE"
  else
    BASE="$DEV_BRANCH"
    warn "release 提交未声明 dev 版本，退化为与 $DEV_BRANCH 当前 tip 比较"
  fi

  build_excludes "$BASE"

  local bad="" line status path
  while IFS= read -r line; do
    if [ -z "$line" ]; then
      continue
    fi
    status="${line%%	*}"
    path="${line#*	}"
    if ! is_excluded "$path"; then
      bad="$bad
  [$status] $path —— 不在排除清单内，却与基准版本不一致"
    elif [ "$status" != "D" ]; then
      bad="$bad
  [$status] $path —— 已排除的文件不应以该状态出现在上线分支"
    fi
  done < <(git -c core.quotepath=false diff --name-status "$BASE" "$VERIFY_REF")

  if [ -n "$bad" ]; then
    printf '%s\n' "$bad" >&2
    die "$VERIFY_REF 的内容不符合「dev − 排除清单」（基准 ${BASE}）"
  fi
  ok "$VERIFY_REF 校验通过：相对基准的差异恰好是排除清单（${#RELEASE_EXCLUDES[@]} 项）"
}

# ── 生成 release 提交 ────────────────────────────────────────
# 前置：当前 HEAD 已是目标基线（PR 模式为 origin/<rel>，direct 模式为本地 <rel>）
# 返回 0 = 已提交；返回 1 = 内容无变化，无需提交
build_release_commit() {
  build_excludes

  # 记录 dev 中真实存在、需要剔除的条目
  local PRESENT=() MISSING="" path
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

  info "以 $DEV_BRANCH 的文件树重建上线内容..."
  git read-tree --reset -u "$DEV_BRANCH"

  for path in "${PRESENT[@]}"; do
    # -f 必需：此时索引内容与 HEAD 不一致，git rm 默认会拒绝执行
    git rm -r -q -f --ignore-unmatch -- "$path" || die "剔除 $path 失败"
  done
  ok "已剔除 ${#PRESENT[@]} 项"

  # 提交前校验：与 dev 的差异必须恰好是排除清单
  local EXFILE LEAK
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
    die "以上文件不在排除清单内却未同步到上线分支，请检查 RELEASE_EXCLUDES"
  fi
  ok "校验通过：相对 $DEV_BRANCH 的差异仅为排除项"

  if git diff --cached --quiet; then
    return 1
  fi

  local DEV_SHA
  DEV_SHA="$(git rev-parse --short "$DEV_BRANCH")"
  git commit -q -m "release: 同步 $DEV_BRANCH@$DEV_SHA

由 scripts/sync-master.sh 生成：内容 = $DEV_BRANCH 代码 − 开发文档与测试脚本。
合入前必须通过 CI 与 Code Review。"
  ok "release 提交 $(git rev-parse --short HEAD)"
  return 0
}

# 把 git remote 的 SSH / HTTPS 地址转成网页地址，用于打印 PR 链接
web_url() {
  local url
  url="$(git remote get-url origin)"
  url="${url%.git}"
  url="${url#git@}"
  url="${url/:/\/}"
  if [ "${url#http}" = "$url" ]; then
    url="https://$url"
  fi
  printf '%s' "$url"
}

# ── 模式：PR（默认）──────────────────────────────────────────
cmd_pr() {
  git diff --quiet || die "工作区有未提交改动，先 commit 或 stash"
  git diff --cached --quiet || die "暂存区有未提交改动，先 commit 或 stash"

  info "拉取远端..."
  git fetch origin --quiet || die "git fetch 失败"

  local DEV_SHA BRANCH
  DEV_SHA="$(git rev-parse --short "$DEV_BRANCH")"
  BRANCH="release/sync-$DEV_SHA"

  info "基于 origin/${REL_BRANCH} 创建 ${BRANCH}（源 ${DEV_BRANCH}@${DEV_SHA}）"
  git checkout -B "$BRANCH" "origin/$REL_BRANCH" --quiet

  if ! build_release_commit; then
    ok "$REL_BRANCH 已与 $DEV_BRANCH 一致（排除项之外无变化），无需发版"
    git checkout "$DEV_BRANCH" --quiet
    return 0
  fi

  ok "推送 $BRANCH"
  # release/* 是一次性分支，覆盖它自己的旧版本是安全的（--force-with-lease 仍会
  # 拒绝覆盖别人的提交），这样同一个 dev 版本重复执行也不会因历史不同而推不上去。
  git push --force-with-lease origin "$BRANCH"

  local URL
  URL="$(web_url)"
  printf '\n'
  ok "下一步：创建 PR，等待 CI 全绿 + Code Review"
  printf '   %s/compare/%s...%s?expand=1\n\n' "$URL" "$REL_BRANCH" "$BRANCH"
  printf '   合入后 master 只多这一个 release 提交。服务器更新：\n'
  printf '     cd /opt/orbit && git pull --ff-only origin %s && docker compose build && docker compose up -d\n\n' "$REL_BRANCH"

  git checkout "$DEV_BRANCH" --quiet
  ok "已切回 $DEV_BRANCH"
}

# ── 模式：--direct（应急直推，绕过门禁）──────────────────────
cmd_direct() {
  printf '\033[33m%s\033[0m\n' \
    "! --direct 会绕过 CI 与 Code Review 直接改写上线分支，仅限线上回滚等紧急场景。"
  printf '  确认继续请输入 yes：'
  local answer=""
  read -r answer
  [ "$answer" = "yes" ] || die "已取消"

  git diff --quiet || die "工作区有未提交改动，先 commit 或 stash"
  git diff --cached --quiet || die "暂存区有未提交改动，先 commit 或 stash"

  info "拉取远端..."
  git fetch origin --quiet || die "git fetch 失败"

  git checkout "$REL_BRANCH" --quiet
  if ! git merge --ff-only "origin/$REL_BRANCH" --quiet 2>/dev/null; then
    die "本地 $REL_BRANCH 与 origin/$REL_BRANCH 已分叉，请先手工处理"
  fi

  if ! build_release_commit; then
    ok "无需提交"
    git checkout "$DEV_BRANCH" --quiet
    return 0
  fi

  git push origin "$REL_BRANCH"
  ok "已直推 ${REL_BRANCH}（未经 review，请尽快补一次 PR 说明）"
  git checkout "$DEV_BRANCH" --quiet
}

# ── 分发 ─────────────────────────────────────────────────────
if [ "$MODE" = "verify" ]; then
  cmd_verify
elif [ "$MODE" = "direct" ]; then
  cmd_direct
else
  cmd_pr
fi

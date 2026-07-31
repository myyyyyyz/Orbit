#!/usr/bin/env bash
set -euo pipefail

# ================================================================
# Agent Loop CLI Runner
# 零依赖 bash 脚本，通过 curl 调用 LLM API，无需 CodeBuddy。
# 支持 Anthropic / OpenAI / 任何兼容 OpenAI 的 API。
#
# 用法:
#   export LLM_API_KEY=sk-xxx
#   ./run-loop.sh --api anthropic --model claude-sonnet-4-20250514
#   ./run-loop.sh --api openai --model gpt-4o --project /path/to/project
# ================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$SCRIPT_DIR/memory"
SCENES_DIR="$SCRIPT_DIR/scenes"
AGENTS_DIR="$SCRIPT_DIR/agents"
PROJECT_SPEC="$SCRIPT_DIR/project/project-spec.md"

# ---- Defaults ----
API="${LLM_API:-openai}"
MODEL="${LLM_MODEL:-gpt-4o}"
BASE_URL="${LLM_BASE_URL:-}"
PROJECT_DIR="$SCRIPT_DIR"
API_KEY="${LLM_API_KEY:-}"
MAX_ITER=3           # 单 case 最大退回次数
CHECKPOINT_INTERVAL=10

# ---- Parse args ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api) API="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --project) PROJECT_DIR="$2"; shift 2 ;;
    --checkpoint) CHECKPOINT_INTERVAL="$2"; shift 2 ;;
    --max-iter) MAX_ITER="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

# ---- Validate ----
if [[ -z "$API_KEY" ]]; then
  echo "❌ 需要 API Key。请设置 LLM_API_KEY 环境变量。"
  echo "   export LLM_API_KEY=sk-xxx"
  exit 1
fi

if [[ ! -f "$PROJECT_SPEC" ]]; then
  echo "❌ 未找到 project-spec.md（在 $PROJECT_SPEC）"
  echo "   请确保在 agent loop 目录或其子目录下运行。"
  exit 1
fi

# ---- Resolve API endpoint ----
case "$API" in
  anthropic)
    API_URL="${BASE_URL:-https://api.anthropic.com/v1/messages}"
    API_TYPE="anthropic"
    ;;
  openai)
    API_URL="${BASE_URL:-https://api.openai.com/v1/chat/completions}"
    API_TYPE="openai"
    ;;
  *)
    API_URL="$BASE_URL"
    API_TYPE="openai"  # default to OpenAI-compatible
    ;;
esac

# ---- Colors ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; }

# ================================================================
# LLM Call Wrapper
# ================================================================
call_llm() {
  local system_prompt="$1"   # Agent 定义（从 .md 文件读）
  local user_context="$2"    # 上下文（plan / output / state 等）
  local output_file="$3"     # 写到哪个文件

  local max_retries=3
  local retry_delays=(1 2 4)  # 指数退避秒数
  local attempt=0

  while [[ $attempt -lt $max_retries ]]; do
    info "正在调用 $API ($MODEL)... (attempt $((attempt + 1))/$max_retries)"

    local payload
    local response
    local http_code
    local curl_exit=0

    if [[ "$API_TYPE" == "anthropic" ]]; then
      payload=$(jq -n \
        --arg model "$MODEL" \
        --arg system "$system_prompt" \
        --arg user "$user_context" \
        '{
          model: $model,
          system: $system,
          messages: [{role: "user", content: $user}],
          max_tokens: 64000
        }')

      # 写临时文件以获取 HTTP 状态码
      local tmp_resp="/tmp/orbit_llm_resp_$$"
      http_code=$(curl -s -w "%{http_code}" -o "$tmp_resp" \
        --connect-timeout 15 --max-time 120 \
        -X POST "$API_URL" \
        -H "x-api-key: $API_KEY" \
        -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d "$payload") || curl_exit=$?

      if [[ $curl_exit -ne 0 ]]; then
        warn "LLM 调用网络错误 (curl exit=$curl_exit)，将重试..."
        attempt=$((attempt + 1))
        [[ $attempt -lt $max_retries ]] && sleep "${retry_delays[$((attempt - 1))]}"
        continue
      fi

      # 4xx 错误不重试（认证/参数问题）
      if [[ "$http_code" =~ ^4[0-9][0-9]$ ]]; then
        fail "LLM API 返回 4xx ($http_code)，不重试"
        jq -r '.error.message // "HTTP '"$http_code"'"' "$tmp_resp" 2>/dev/null || echo "HTTP $http_code"
        rm -f "$tmp_resp"
        return 1
      fi

      # 5xx 或空响应可重试
      if [[ "$http_code" =~ ^5[0-9][0-9]$ ]] || [[ "$http_code" == "000" ]]; then
        warn "LLM API 返回 $http_code，将重试..."
        attempt=$((attempt + 1))
        [[ $attempt -lt $max_retries ]] && sleep "${retry_delays[$((attempt - 1))]}"
        continue
      fi

      jq -r '.content[0].text // .error.message // "ERROR: empty response"' "$tmp_resp"
      rm -f "$tmp_resp"
      return 0
    else
      payload=$(jq -n \
        --arg model "$MODEL" \
        --arg system "$system_prompt" \
        --arg user "$user_context" \
        '{
          model: $model,
          messages: [
            {role: "system", content: $system},
            {role: "user", content: $user}
          ]
        }')

      local tmp_resp="/tmp/orbit_llm_resp_$$"
      http_code=$(curl -s -w "%{http_code}" -o "$tmp_resp" \
        --connect-timeout 15 --max-time 120 \
        -X POST "$API_URL" \
        -H "Authorization: Bearer $API_KEY" \
        -H "content-type: application/json" \
        -d "$payload") || curl_exit=$?

      if [[ $curl_exit -ne 0 ]]; then
        warn "LLM 调用网络错误 (curl exit=$curl_exit)，将重试..."
        attempt=$((attempt + 1))
        [[ $attempt -lt $max_retries ]] && sleep "${retry_delays[$((attempt - 1))]}"
        continue
      fi

      # 4xx 错误不重试
      if [[ "$http_code" =~ ^4[0-9][0-9]$ ]]; then
        fail "LLM API 返回 4xx ($http_code)，不重试"
        jq -r '.error.message // "HTTP '"$http_code"'"' "$tmp_resp" 2>/dev/null || echo "HTTP $http_code"
        rm -f "$tmp_resp"
        return 1
      fi

      # 5xx 或空响应可重试
      if [[ "$http_code" =~ ^5[0-9][0-9]$ ]] || [[ "$http_code" == "000" ]]; then
        warn "LLM API 返回 $http_code，将重试..."
        attempt=$((attempt + 1))
        [[ $attempt -lt $max_retries ]] && sleep "${retry_delays[$((attempt - 1))]}"
        continue
      fi

      jq -r '.choices[0].message.content // .error.message // "ERROR: empty response"' "$tmp_resp"
      rm -f "$tmp_resp"
      return 0
    fi
  done

  fail "LLM 调用失败：已达最大重试次数 ($max_retries)"
  return 1
}

# ================================================================
# 场景发现
# ================================================================
find_pending_scenes() {
  local scenes=()
  for f in "$SCENES_DIR"/*.md; do
    [[ "$(basename "$f")" == "_template.md" ]] && continue
    scenes+=("$f")
  done
  echo "${scenes[@]}"
}

# ================================================================
# 主循环
# ================================================================
main() {
  echo ""
  echo "═══════════════════════════════════════════"
  echo "  Agent Loop — 多智能体协作开发框架"
  echo "  API: $API | Model: $MODEL"
  echo "═══════════════════════════════════════════"
  echo ""

  # ================================================================
  # Step 0: Master Bootstrap Guard
  # ================================================================
  # Master Agent 是冷启动需求对齐环节，需要交互式对话。
  # run-loop.sh（bash + curl）无法处理交互式对话，因此：
  # - 如果 project-spec.md 含 <待定>，拦截并指引用户先完成 Master 对话
  # - 如果 project-spec.md 已完整，直接进入 Planner
  if grep -q '<待定>' "$PROJECT_SPEC" 2>/dev/null; then
    echo ""
    echo "🔔 ═══════════════════════════════════════════"
    echo "   检测到 project-spec.md 中存在 <待定> 占位符"
    echo "   ═══════════════════════════════════════════"
    echo ""
    echo "   Master Agent 必须先与你对齐需求，流程如下："
    echo ""
    echo "   1. 🔍 读取 project-spec.md，列出所有待定项"
    echo "   2. 🌐 调用 master skill 搜索最佳实践"
    echo "   3. 💬 逐项与你确认：分支、项目类型、完成标准..."
    echo "   4. ✅ 所有 <待定> 填满 + 你说'开始写代码' → Loop 才启动"
    echo ""
    echo "   📋 当前待定项预览："
    grep -n '<待定>' "$PROJECT_SPEC" | head -20 | while IFS=: read -r line content; do
      echo "     行 $line: $content"
    done
    echo ""
    echo "   👉 请回到 Chat 界面，说'开始对齐需求'或'@master 帮我配置项目'"
    echo "   ⛔ Agent Loop 在此终止（等待 Master 完成）"
    echo ""
    exit 0
  fi

  # --- Phase 0: Discovery ---
  info "Phase 0: Discover scenes..."
  local scenes=($(find_pending_scenes))
  if [[ ${#scenes[@]} -eq 0 ]]; then
    warn "没有待处理的场景。继续执行默认流程。"
    scenes=("${SCENES_DIR}/_template.md")
  fi
  ok "找到 ${#scenes[@]} 个场景"

  local case_count=0
  local iteration_count=0

  for scene_file in "${scenes[@]}"; do
    scene_name=$(basename "$scene_file" .md)
    [[ "$scene_name" == "_template" ]] && continue

    case_count=$((case_count + 1))
    iteration_count=0

    echo ""
    echo "───────────────────────────────────────"
    echo "  Case $case_count: $scene_name"
    echo "───────────────────────────────────────"

    while true; do
      iteration_count=$((iteration_count + 1))
      if [[ $iteration_count -gt $MAX_ITER ]]; then
        fail "迭代次数超限 ($MAX_ITER)，升级给人决策"
        echo "  退回历史摘要："
        [[ -f "$MEMORY_DIR/loop-plan.md" ]] && echo "    Plan: $MEMORY_DIR/loop-plan.md"
        [[ -f "$MEMORY_DIR/loop-builder-output.md" ]] && echo "    Output: $MEMORY_DIR/loop-builder-output.md"
        [[ -f "$MEMORY_DIR/loop-review-result.md" ]] && echo "    Review: $MEMORY_DIR/loop-review-result.md"
        exit 1
      fi

      # ============================================================
      # Step 1: Spawn Planner
      # ============================================================
      info "Spawning Planner... (iter $iteration_count)"

      local planner_prompt
      planner_prompt=$(cat "$AGENTS_DIR/planner.md")

      local planner_context
      planner_context=$(cat <<EOF
## 当前场景
$(cat "$scene_file")

## 项目约束
$(cat "$PROJECT_SPEC" 2>/dev/null || echo "（无）")

## 任务状态
$(cat "$MEMORY_DIR/loop-state.md" 2>/dev/null || echo "当前状态: ready")

## 你的任务
产出一份执行计划，写入 loop-plan.md。
包含：执行步骤（每步带 verify）、验证 Gate、维度覆盖矩阵、影响面分析。
EOF
)

      call_llm "$planner_prompt" "$planner_context" "$MEMORY_DIR/loop-plan.md" \
        > "$MEMORY_DIR/loop-plan.md"
      ok "Plan 已写入 $MEMORY_DIR/loop-plan.md"

      # ============================================================
      # Step 2: Spawn Builder
      # ============================================================
      info "Spawning Builder..."

      local builder_prompt
      builder_prompt=$(cat "$AGENTS_DIR/builder.md")

      local builder_context
      builder_context=$(cat <<EOF
## 执行计划
$(cat "$MEMORY_DIR/loop-plan.md")

## 项目约束
$(cat "$PROJECT_SPEC" 2>/dev/null || echo "（无）")

## 你的任务
严格按计划执行修改。写入 loop-builder-output.md。
EOF
)

      call_llm "$builder_prompt" "$builder_context" "$MEMORY_DIR/loop-builder-output.md" \
        > "$MEMORY_DIR/loop-builder-output.md"
      ok "Builder 输出已写入 $MEMORY_DIR/loop-builder-output.md"

      # ============================================================
      # Step 2.5: Builder Code Execution (P1 增强)
      # ============================================================
      # 从 Builder 输出提取 diff 代码块并尝试应用到项目目录
      info "Executing Builder output..."
      local exec_result=""
      local exec_success=false
      local project_dir="$PROJECT_DIR"  # 可通过 --project 参数指定

      # 提取 ```diff 代码块
      local diff_blocks
      diff_blocks=$(grep -n '```diff' "$MEMORY_DIR/loop-builder-output.md" 2>/dev/null || true)

      if [[ -n "$diff_blocks" && -d "$project_dir" ]]; then
        # 在项目目录创建临时分支并应用 diff
        local exec_tmp="/tmp/orbit_exec_$$"
        mkdir -p "$exec_tmp"

        # 提取所有 diff 代码块到一个文件
        python3 -c "
import re, sys
with open('$MEMORY_DIR/loop-builder-output.md') as f:
    content = f.read()
blocks = re.findall(r'\`\`\`diff\n(.*?)\`\`\`', content, re.DOTALL)
with open('$exec_tmp/builder.diff', 'w') as out:
    out.write('\n'.join(blocks))
print(f'Extracted {len(blocks)} diff block(s)')
" > "$exec_tmp/extract.log" 2>&1

        ok "提取结果: $(cat "$exec_tmp/extract.log")"

        # 尝试在项目目录应用 diff
        if [[ -f "$exec_tmp/builder.diff" ]]; then
          if (cd "$project_dir" && git apply --check "$exec_tmp/builder.diff" 2>"$exec_tmp/check.log"); then
            ok "Diff 格式验证通过，应用变更..."
            (cd "$project_dir" && git apply "$exec_tmp/builder.diff" 2>&1) && exec_success=true
          else
            warn "Diff 格式不兼容 git apply（可能为示意性代码块），跳过自动执行"
            cat "$exec_tmp/check.log" | head -3 | while read line; do warn "  $line"; done
          fi
        fi
        rm -rf "$exec_tmp"
      else
        warn "未找到 diff 代码块或项目目录不存在，跳过自动执行"
      fi

      # 写入执行日志
      exec_result="## Builder Code Execution Log\n\n"
      exec_result+="- **Diff blocks found**: $([[ -n "$diff_blocks" ]] && echo 'yes' || echo 'no')\n"
      exec_result+="- **Auto-applied**: $([[ "$exec_success" == true ]] && echo 'yes' || echo 'no')\n"
      exec_result+="- **Executor**: run-loop.sh Step 2.5 (git apply + dry-run)\n"
      echo -e "\n$exec_result" >> "$MEMORY_DIR/loop-builder-output.md"

      # ============================================================
      # Step 3: Spawn Reviewer
      # ============================================================
      info "Spawning Reviewer..."

      local reviewer_prompt
      reviewer_prompt=$(cat "$AGENTS_DIR/reviewer.md")

      local reviewer_context
      reviewer_context=$(cat <<EOF
## 验证标准
$(cat "$MEMORY_DIR/loop-plan.md" | grep -A999 '## 验证 Gate' || echo "（无 Gate 定义）")

## Builder 做了什么
$(cat "$MEMORY_DIR/loop-builder-output.md")

## 项目约束
$(cat "$PROJECT_SPEC" 2>/dev/null || echo "（无）")

## 你的任务
按两阶段审：Stage 1 Spec Compliance + Stage 2 Code Quality。
写入 loop-review-result.md。
EOF
)

      call_llm "$reviewer_prompt" "$reviewer_context" "$MEMORY_DIR/loop-review-result.md" \
        > "$MEMORY_DIR/loop-review-result.md"

      local verdict
      verdict=$(grep -i "ALL_PASS\|PARTIAL_FAIL\|CRITICAL_FAIL" "$MEMORY_DIR/loop-review-result.md" | head -1 || echo "UNKNOWN")
      ok "Reviewer 结论: $(echo $verdict | tr '[:lower:]' '[:upper:]')"

      # ============================================================
      # Decision
      # ============================================================
      if echo "$verdict" | grep -qi "ALL_PASS"; then
        ok "Case $case_name 通过！"
        break
      elif echo "$verdict" | grep -qi "CRITICAL_FAIL"; then
        fail "Case $case_name CRITICAL_FAIL，升级给人"
        echo ""
        echo "--- Review 详情 ---"
        cat "$MEMORY_DIR/loop-review-result.md"
        exit 1
      else
        warn "Case $case_name 未通过（$verdict），重试 (iter $iteration_count/$MAX_ITER)"
        # 归档当前文件供下一轮参考
        mkdir -p "$MEMORY_DIR/archive/${scene_name}_iter_${iteration_count}"
        cp "$MEMORY_DIR/loop-plan.md" "$MEMORY_DIR/archive/${scene_name}_iter_${iteration_count}/"
        cp "$MEMORY_DIR/loop-builder-output.md" "$MEMORY_DIR/archive/${scene_name}_iter_${iteration_count}/"
        cp "$MEMORY_DIR/loop-review-result.md" "$MEMORY_DIR/archive/${scene_name}_iter_${iteration_count}/"
      fi
    done

    # --- Checkpoint ---
    if [[ $((case_count % CHECKPOINT_INTERVAL)) -eq 0 ]]; then
      echo ""
      echo "═══════════════════════════════════════════"
      echo "  🔔 Checkpoint: 已完成 $case_count 个 case"
      echo "═══════════════════════════════════════════"
      echo ""
      echo "  目前状态："
      echo "  - 累计通过: $case_count"
      echo "  - 当前场景: $scene_name"
      echo ""
      echo -n "  ⏸️  继续吗？[Y/n] "
      read -r response
      if [[ "$response" =~ ^[nN] ]]; then
        info "用户暂停，退出。"
        exit 0
      fi
    fi
  done

  echo ""
  echo "═══════════════════════════════════════════"
  echo "  ✅ All cases passed! ($case_count total)"
  echo "═══════════════════════════════════════════"
}

# ---- Run ----
main "$@"

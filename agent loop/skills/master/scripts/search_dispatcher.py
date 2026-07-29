"""Dispatch technical searches to appropriate platforms based on problem type."""
import sys
import json
import argparse

SEARCH_PATHS = {
    "ai_agent": {
        "primary": [
            "OpenAI (platform.openai.com/docs + cookbook.openai.com)",
            "Anthropic (docs.anthropic.com + anthropic.com/engineering)",
            "AWS AI/ML Blog (aws.amazon.com/blogs/machine-learning)",
            "Google AI (ai.google.dev + deepmind.google)",
            "Microsoft AI (learn.microsoft.com/en-us/azure/ai-services)",
            "Meta AI (ai.meta.com/blog + llama.meta.com)",
        ],
        "secondary": [
            "GitHub (official SDK repos + cookbook repos)",
            "Dev.to",
            "Medium",
            "Hacker News",
            "Reddit (r/MachineLearning, r/LocalLLaMA)",
        ],
        "github_query": None,  # GitHub is round 2 for AI topics
        "notes": (
            "AI/Agent topics: OFFICIAL SOURCES FIRST. "
            "Search at least 3 official vendor sources before GitHub. "
            "Prioritize content from last 3 months. "
            "Content > 6 months must be cross-validated. "
            "Content > 1 year is likely obsolete. "
            "When vendors conflict, prioritize the model provider's recommendation."
        ),
        "official_search_sites": [
            "platform.openai.com",
            "cookbook.openai.com",
            "docs.anthropic.com",
            "anthropic.com/engineering",
            "aws.amazon.com/blogs/machine-learning",
            "docs.aws.amazon.com/bedrock",
            "ai.google.dev",
            "deepmind.google",
            "blog.google/technology/ai",
            "learn.microsoft.com/en-us/azure/ai-services",
            "learn.microsoft.com/en-us/semantic-kernel",
            "ai.meta.com/blog",
            "llama.meta.com",
        ],
    },
    "bug": {
        "primary": ["GitHub Issues", "Stack Overflow"],
        "secondary": ["SegmentFault", "Official Docs"],
        "github_query": 'search/issues?q="{error}"',
        "notes": "Use exact error message in quotes. Strip local paths/line numbers.",
    },
    "best_practice": {
        "primary": ["GitHub Repositories", "InfoQ"],
        "secondary": ["掘金", "Medium"],
        "github_query": "search/repositories?q={keyword}&s=stars",
        "notes": "Sort by stars. Read README's 'Why' section and example/ directory.",
    },
    "tech_selection": {
        "primary": ["GitHub Repositories", "Hacker News"],
        "secondary": ["InfoQ", "掘金"],
        "github_query": "search/repositories?q={keyword}+vs&s=stars",
        "notes": "Compare stars, recent activity, community health.",
    },
    "performance": {
        "primary": ["GitHub benchmark/", "Stack Overflow"],
        "secondary": ["博客园", "DZone"],
        "github_query": "search/code?q={keyword}+benchmark",
        "notes": "Look for benchmark data. Verify reproducibility.",
    },
    "architecture": {
        "primary": ["InfoQ", "High Scalability"],
        "secondary": ["阿里云社区", "腾讯云社区"],
        "github_query": "search/repositories?q={keyword}+architecture&s=stars",
        "notes": "Look for articles with specific QPS/scale numbers, not abstract designs.",
    },
    "security": {
        "primary": ["GitHub Security Advisories", "OWASP"],
        "secondary": ["CVE Details", "NVD"],
        "github_query": "advisories?query={keyword}",
        "notes": "CVE score > 7.0 requires immediate attention.",
    },
    "frontend": {
        "primary": ["GitHub Repositories", "MDN"],
        "secondary": ["CSS-Tricks", "掘金"],
        "github_query": "search/repositories?q={keyword}+component&s=stars",
        "notes": "MDN is authoritative for Web API compatibility.",
    },
    "devops": {
        "primary": ["DevOps Weekly", "GitHub Actions Marketplace"],
        "secondary": ["华为云社区", "The New Stack"],
        "github_query": "search/repositories?q={keyword}+ci&s=stars",
        "notes": "CI/CD configurations should be tested before production use.",
    },
    "algorithm": {
        "primary": ["LeetCode"],
        "secondary": ["AcWing", "牛客"],
        "github_query": None,
        "notes": "Prioritize solutions with time/space complexity analysis.",
    },
    "domestic_tech": {
        "primary": ["开源中国", "Gitee"],
        "secondary": ["华为云社区", "阿里云社区"],
        "github_query": None,
        "notes": "For domestic/信创 ecosystem technologies.",
    },
}


def get_plan(problem_type: str, keyword: str) -> dict:
    """Generate a search plan for the given problem type."""
    if problem_type not in SEARCH_PATHS:
        # Default: treat as bug
        problem_type = "bug"

    path = SEARCH_PATHS[problem_type]
    plan = {
        "problem_type": problem_type,
        "keyword": keyword,
        "round_1": {
            "platforms": ["GitHub"] + path["primary"],
            "github_query": (path.get("github_query", "") or "").replace("{keyword}", keyword).replace("{error}", keyword),
            "notes": path["notes"],
        },
        "round_2": {
            "platforms": path["secondary"],
            "trigger": "Round 1 results insufficient or need cross-validation",
        },
        "memory_checklist": [
            "Solution is confirmed by ≥ 2 independent sources",
            "Solution is from recent (< 1 year) content",
            "Solution is applicable to current project stack",
            "Knowledge is reusable beyond current issue",
        ],
    }
    return plan


def classify_problem(user_input: str) -> str:
    """Auto-classify problem type from user input."""
    keywords = {
        "ai_agent": [
            # AI / LLM
            "ai", "llm", "大模型", "大语言模型", "language model", "gpt", "claude", "gemini",
            "llama", "deepseek", "chatgpt", "copilot",
            # Agent
            "agent", "智能体", "ai agent", "autonomous agent", "agentic",
            "multi-agent", "agent框架", "agent framework",
            # RAG
            "rag", "retrieval augmented", "检索增强", "embedding", "向量",
            "vector database", "knowledge base", "知识库",
            # Prompt
            "prompt", "提示词", "提示工程", "prompt engineering", "few-shot",
            "chain of thought", "思维链", "system prompt",
            # AI SDK / API
            "openai api", "anthropic api", "anthropic sdk", "claude api",
            "gemini api", "bedrock", "vertex ai", "azure openai",
            # AI framework
            "langchain", "llamaindex", "autogen", "semantic kernel",
            "crewai", "dspy", "langgraph", "flowise",
            # AI 应用
            "function calling", "tool use", "tool calling", "assistants api",
            "fine-tuning", "微调", "rlhf", "ai安全", "ai safety",
            # Agent Harness
            "harness", "hook", "hooks", "pretooluse", "posttooluse",
            "sessionstart", "subagentstop", "permissionrequest",
            "settings.json", "claude settings", "context: fork",
            "context fork", "fork context", "sub-agent", "sub agent",
            "subagent", "子agent", "子 agent", "tool orchestration",
            "工具编排", "tool 权限", "allowed-tools", "allowed tools",
            "skill 设计", "skill design", "skill 规范", "skill frontmatter",
            "claude code 配置", "claude code skill",
        ],
        "performance": ["慢", "卡", "性能", "优化", "slow", "performance", "optimize", "超时", "timeout"],
        "security": ["安全", "漏洞", "注入", "security", "vulnerability", "xss", "sql injection"],
        "architecture": ["架构", "设计", "重构", "architecture", "design", "refactor", "拆分"],
        "tech_selection": ["选型", "选择", "推荐", "哪个好", "vs", "对比", "comparison"],
        "best_practice": ["最佳实践", "规范", "best practice", "标准", "standard", "推荐做法"],
        "frontend": ["前端", "css", "布局", "响应式", "动画", "组件"],
        "devops": ["部署", "ci", "cd", "k8s", "docker", "监控", "日志"],
        "algorithm": ["算法", "leetcode", "复杂度", "排序", "搜索"],
        "domestic_tech": ["国产", "信创", "鲲鹏", "鸿蒙", "欧拉"],
    }

    for ptype, words in keywords.items():
        if any(w in user_input.lower() for w in words):
            return ptype

    return "best_practice"  # default


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dispatch technical search to platforms")
    parser.add_argument("query", help="User's technical question")
    parser.add_argument("--type", help="Problem type override (auto-detected if not provided)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    ptype = args.type or classify_problem(args.query)
    plan = get_plan(ptype, args.query)

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(f"\n  Problem Type: {plan['problem_type']}")
        print(f"\n  ── Round 1 (REQUIRED) ──")
        for p in plan["round_1"]["platforms"]:
            print(f"    → {p}")
        if plan["round_1"]["github_query"]:
            print(f"    GitHub: {plan['round_1']['github_query']}")
        print(f"\n  ── Round 2 (if needed) ──")
        for p in plan["round_2"]["platforms"]:
            print(f"    → {p}")
        print(f"\n  [Memory] Only convert to memory if all checklist items pass.")
        print()

"""
新手引导模块

首次使用时引导用户选择角色，自动加载预设 Skill 模板。
"""

from typing import Optional

ROLE_TEMPLATES = {
    "developer": {
        "label": "开发者",
        "icon": "💻",
        "desc": "写代码、做架构、调性能",
        "recommended_skills": ["master", "review", "ponytail", "pipeline-e2e-auditor"],
        "default_preferences": {
            "output_format": "code_first",
            "code_comments": "chinese",
            "test_level": "full",
        },
        "quick_actions": [
            "帮我写一个 FastAPI 接口",
            "审查这段代码",
            "搜索 XX 技术的最佳实践",
        ],
    },
    "pm": {
        "label": "产品经理",
        "icon": "📋",
        "desc": "写需求、做规划、跟进度",
        "recommended_skills": ["sage", "idea-to-plan", "project-launcher"],
        "default_preferences": {
            "output_format": "document_first",
            "code_comments": "none",
            "test_level": "smoke",
        },
        "quick_actions": [
            "帮我把这个 idea 转成方案",
            "做一个项目规划",
            "分析一下这个决策的利弊",
        ],
    },
    "manager": {
        "label": "管理者",
        "icon": "👔",
        "desc": "做决策、管团队、看数据",
        "recommended_skills": ["sage", "master", "logos"],
        "default_preferences": {
            "output_format": "summary_first",
            "code_comments": "none",
            "test_level": "skip",
        },
        "quick_actions": [
            "用 MECE 分析这个问题",
            "帮我做技术选型决策",
            "总结今天的对话要点",
        ],
    },
    "student": {
        "label": "学生",
        "icon": "📚",
        "desc": "学习知识、做作业、写论文",
        "recommended_skills": ["master", "sage", "logos"],
        "default_preferences": {
            "output_format": "explain_first",
            "code_comments": "english",
            "test_level": "smoke",
        },
        "quick_actions": [
            "解释一下 XX 概念",
            "帮我搜索 XX 的学习资料",
            "总结今天学到的知识",
        ],
    },
    "enterprise": {
        "label": "企业用户",
        "icon": "🏢",
        "desc": "管理知识库、团队协作、数据分析",
        "recommended_skills": ["master", "sage", "logos", "review", "pipeline-e2e-auditor"],
        "default_preferences": {
            "output_format": "report_first",
            "code_comments": "chinese",
            "test_level": "full",
            "multi_user": True,
        },
        "quick_actions": [
            "上传企业文档建立知识库",
            "根据知识库回答问题",
            "审计这个 pipeline",
        ],
    },
}


def get_onboarding_template() -> dict:
    """获取新手引导模板（首次使用时展示）"""
    return {
        "title": "欢迎使用 AI Agent 系统",
        "subtitle": "选择你的角色，我们会为你推荐最合适的工具组合",
        "roles": [
            {
                "key": k,
                "label": v["label"],
                "icon": v["icon"],
                "desc": v["desc"],
                "quick_actions_count": len(v["quick_actions"]),
            }
            for k, v in ROLE_TEMPLATES.items()
        ],
    }


def get_role_config(role: str) -> Optional[dict]:
    """获取指定角色的完整配置"""
    return ROLE_TEMPLATES.get(role)


def get_all_roles() -> dict:
    """获取所有角色"""
    return {k: {"label": v["label"], "icon": v["icon"], "desc": v["desc"]} for k, v in ROLE_TEMPLATES.items()}

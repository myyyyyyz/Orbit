"""onboarding/ — 新手引导模块测试"""
from app.onboarding import get_onboarding_template, get_role_config, get_all_roles, ROLE_TEMPLATES


def test_template_structure():
    t = get_onboarding_template()
    assert t["title"]
    assert t["subtitle"]
    assert len(t["roles"]) == len(ROLE_TEMPLATES)
    for role in t["roles"]:
        assert set(role.keys()) == {"key", "label", "icon", "desc", "quick_actions_count"}
        assert role["quick_actions_count"] > 0


def test_template_roles_match_templates():
    keys = {r["key"] for r in get_onboarding_template()["roles"]}
    assert keys == set(ROLE_TEMPLATES.keys())


def test_get_all_roles():
    roles = get_all_roles()
    assert "developer" in roles
    assert "pm" in roles
    assert roles["developer"]["label"] == "开发者"
    for v in roles.values():
        assert set(v.keys()) == {"label", "icon", "desc"}


def test_get_role_config_complete():
    config = get_role_config("developer")
    assert config["label"] == "开发者"
    assert "master" in config["recommended_skills"]
    assert config["default_preferences"]["output_format"] == "code_first"
    assert len(config["quick_actions"]) == 3


def test_get_role_config_enterprise_multi_user():
    config = get_role_config("enterprise")
    assert config["default_preferences"]["multi_user"] is True


def test_get_role_config_nonexistent():
    assert get_role_config("no_such_role") is None
    assert get_role_config("") is None

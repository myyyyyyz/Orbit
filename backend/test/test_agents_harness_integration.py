"""P1/P2/P3 harness 增强测试：effects 可逆副作用、资产注册表、测试分层 gate。

覆盖:
- effects: create/modify/delete 三种落盘 + 精确回滚 + 路径穿越防护
- registry: agent-loop skills/scenes/agents 服务发现
- gate.check_verification: skip/smoke/full 三档验证深度校验
- orchestrator: _max_test_level 计算 + _apply_build 返回 effects
"""

import json
import os
from pathlib import Path

import pytest


# ── P1: effects 可逆副作用 ────────────────────────────────────────

class TestEffects:
    def test_apply_create_then_revert(self, tmp_path):
        from app.agents.effects import apply_build_files, revert_effects

        res = apply_build_files(
            [{"path": "hello.py", "action": "create", "content": "print('hi')\n"}],
            str(tmp_path),
        )
        assert res["applied"] == 1
        assert res["skipped"] == 0
        assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert res["effects"][0]["action"] == "create"

        # 回滚：create → 删除
        rv = revert_effects(res["effects"], str(tmp_path))
        assert rv["reverted"] == 1
        assert not (tmp_path / "hello.py").exists()

    def test_apply_modify_then_revert_restores_original(self, tmp_path):
        from app.agents.effects import apply_build_files, revert_effects

        f = tmp_path / "app.py"
        f.write_text("original\n", encoding="utf-8")
        res = apply_build_files(
            [{"path": "app.py", "action": "modify", "content": "modified\n"}],
            str(tmp_path),
        )
        assert res["effects"][0]["original_content"] == "original\n"
        assert f.read_text(encoding="utf-8") == "modified\n"

        rv = revert_effects(res["effects"], str(tmp_path))
        assert rv["reverted"] == 1
        assert f.read_text(encoding="utf-8") == "original\n"

    def test_apply_delete_then_revert_restores(self, tmp_path):
        from app.agents.effects import apply_build_files, revert_effects

        f = tmp_path / "old.py"
        f.write_text("to be deleted\n", encoding="utf-8")
        res = apply_build_files(
            [{"path": "old.py", "action": "delete", "content": ""}],
            str(tmp_path),
        )
        assert not f.exists()
        assert res["effects"][0]["original_content"] == "to be deleted\n"

        rv = revert_effects(res["effects"], str(tmp_path))
        assert rv["reverted"] == 1
        assert f.read_text(encoding="utf-8") == "to be deleted\n"

    def test_path_traversal_rejected(self, tmp_path):
        from app.agents.effects import apply_build_files

        res = apply_build_files(
            [{"path": "../evil.py", "action": "create", "content": "x"}],
            str(tmp_path),
        )
        assert res["applied"] == 0
        assert res["skipped"] == 1
        assert not (tmp_path.parent / "evil.py").exists()

    def test_revert_path_traversal_rejected(self, tmp_path):
        from app.agents.effects import revert_effects

        rv = revert_effects([{"path": "../evil.py", "action": "create", "original_content": ""}], str(tmp_path))
        assert rv["reverted"] == 0
        assert len(rv["failed"]) == 1


# ── P2: 资产注册表 ────────────────────────────────────────────────

class TestRegistry:
    def test_registry_discovers_orbit_assets(self):
        from app.agents.registry import AssetRegistry

        # Orbit 根：backend/test/ 上 2 级
        root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        reg = AssetRegistry(root)
        reg.load()

        # skills：至少发现 loop-engine / master
        skill_ids = {s.id for s in reg.list_skills()}
        assert "loop-engine" in skill_ids, f"应发现 loop-engine skill，实际: {sorted(skill_ids)}"

        # agents：planner / builder / reviewer
        agent_ids = {a.id for a in reg.list_agents()}
        assert {"planner", "builder", "reviewer"} <= agent_ids

        # 按 key 查询
        loop_engine = reg.get_skill("loop-engine")
        assert loop_engine is not None
        assert loop_engine.type == "harness"

    def test_registry_skills_summary_injectable(self):
        from app.agents.registry import default_registry

        summary = default_registry().skills_summary()
        assert "可用技能清单" in summary
        assert "loop-engine" in summary


# ── P3: 测试分层 gate ─────────────────────────────────────────────

class TestLayeredGate:
    def _gate(self, tmp_path):
        from app.agents.gate import LoopGate

        gate = LoopGate(str(tmp_path))
        gate.load()
        return gate

    def test_skip_level_no_requirement(self, tmp_path):
        g = self._gate(tmp_path)
        r = g.check_verification([], "skip")
        assert r.passed is True  # skip 不要求验证

    def test_smoke_requires_verification(self, tmp_path):
        g = self._gate(tmp_path)
        r = g.check_verification([], "smoke")
        assert r.passed is False
        assert any("至少 1 条验证命令" in w for w in r.warnings)

    def test_smoke_allows_lint(self, tmp_path):
        g = self._gate(tmp_path)
        r = g.check_verification(["npm run lint"], "smoke")
        assert r.passed is True

    def test_full_requires_test_command(self, tmp_path):
        g = self._gate(tmp_path)
        r = g.check_verification(["python3 -c 'print(1)'"], "full")
        assert r.passed is False
        assert any("要求测试命令" in w for w in r.warnings)

    def test_full_passes_with_pytest(self, tmp_path):
        g = self._gate(tmp_path)
        r = g.check_verification(["python3 -m pytest test_x.py -q"], "full")
        assert r.passed is True

    def test_never_abort(self, tmp_path):
        """分层校验只产出证据，不阻止执行（与 denylist 不同）。"""
        g = self._gate(tmp_path)
        r = g.check_verification([], "full")
        assert r.abort is False


# ── orchestrator 辅助 ─────────────────────────────────────────────

class TestOrchestratorHelpers:
    def test_max_test_level(self):
        from app.agents.orchestrator import _max_test_level
        from app.agents.schemas import Plan, PlanStep

        plan = Plan(task_name="t", steps=[
            PlanStep(index=1, desc="a", verify="v", test_level="skip"),
            PlanStep(index=2, desc="b", verify="v", test_level="full"),
        ])
        assert _max_test_level(plan) == "full"

        plan2 = Plan(task_name="t", steps=[
            PlanStep(index=1, desc="a", verify="v", test_level="smoke"),
        ])
        assert _max_test_level(plan2) == "smoke"

        plan3 = Plan(task_name="t", steps=[])
        assert _max_test_level(plan3) == "skip"

    def test_apply_build_returns_effects(self, tmp_path, monkeypatch):
        from app.agents.orchestrator import _apply_build
        from app.agents.schemas import BuildOutput

        def fake_resolve(pd):
            return str(tmp_path)

        monkeypatch.setattr("app.agents.orchestrator._resolve_safe_project_dir", fake_resolve)

        build = BuildOutput(
            summary="t",
            changed_files=[{"path": "a.py", "action": "create", "content": "x = 1\n"}],
        )
        res = _apply_build(build, "proj")
        assert res["applied"] == 1
        assert len(res["effects"]) == 1
        assert res["effects"][0]["path"] == "a.py"
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"

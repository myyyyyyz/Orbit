"""Agent 资产注册表（P2）：发现 agent-loop 目录下的 skills / scenes / agents。

借鉴 deepseek-harness 的"服务键发现"：资产按稳定 key（frontmatter name）注册，
宿主（orchestrator）不硬编码依赖，运行时按需查询。

资产来源（全部为 agent-loop/ 下的 markdown 资产）:
- skills/*/SKILL.md   → SkillManifest（type=harness/tool/...，可含 requires 依赖声明）
- scenes/*.md         → SceneManifest（type=frontend/backend/fullstack，dev_server 配置）
- agents/*.md         → AgentManifest（角色定义，tools/permissionMode）

注册表是只读的（安全规则：不做任何写操作）；解析失败的文件跳过并记录 warning，
不影响 loop 主流程。
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# agent-loop 目录（相对 Orbit 根）
AGENT_LOOP_DIRNAME = "agent-loop"


@dataclass
class SkillManifest:
    """skill 包 manifest（来自 SKILL.md frontmatter）。"""

    id: str
    name: str = ""
    description: str = ""
    type: str = "tool"
    version: str = "0.0.0"
    requires: list[str] = field(default_factory=list)
    path: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "type": self.type, "version": self.version, "requires": self.requires,
            "path": self.path,
        }


@dataclass
class SceneManifest:
    """场景 manifest（来自 scenes/*.md frontmatter + 内嵌 yaml 块）。"""

    id: str
    name: str = ""
    type: str = "backend"
    description: str = ""
    dev_server: Optional[dict] = None
    path: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "type": self.type,
            "description": self.description, "dev_server": self.dev_server, "path": self.path,
        }


@dataclass
class AgentManifest:
    """Agent 角色 manifest（来自 agents/*.md frontmatter）。"""

    id: str
    name: str = ""
    description: str = ""
    tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"
    path: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "tools": self.tools, "permission_mode": self.permission_mode, "path": self.path,
        }


class AssetRegistry:
    """agent-loop 资产注册表：扫描 → 解析 frontmatter → 按 key 查询。"""

    def __init__(self, project_root: str):
        self.project_root = os.path.realpath(project_root) if project_root else ""
        self.agent_loop_dir = os.path.join(self.project_root, AGENT_LOOP_DIRNAME)
        self.skills: dict[str, SkillManifest] = {}
        self.scenes: dict[str, SceneManifest] = {}
        self.agents: dict[str, AgentManifest] = {}
        self._loaded = False

    def load(self):
        """扫描并解析全部资产。幂等，重复调用不重复扫描。"""
        if self._loaded:
            return
        self._scan_skills()
        self._scan_scenes()
        self._scan_agents()
        self._loaded = True
        logger.info(
            "Registry 加载完成: %d skills, %d scenes, %d agents (root=%s)",
            len(self.skills), len(self.scenes), len(self.agents), self.project_root,
        )

    # ── frontmatter 解析 ──────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(text: str) -> dict:
        """解析 markdown 开头的 YAML frontmatter（--- 包裹）。失败返回 {}。"""
        if not text.startswith("---"):
            return {}
        end = text.find("\n---", 3)
        if end == -1:
            return {}
        try:
            data = yaml.safe_load(text[3:end].strip()) or {}
            return data if isinstance(data, dict) else {}
        except Exception as e:  # noqa: BLE001
            logger.warning("frontmatter 解析失败: %s", e)
            return {}

    # ── skills ────────────────────────────────────────────────────

    def _scan_skills(self):
        skills_dir = Path(self.agent_loop_dir) / "skills"
        if not skills_dir.is_dir():
            return
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                # 允许子目录结构 skills/<pkg>/skills/SKILL.md（如 ponytail/obsidian-skills）
                nested = skill_dir / "skills" / "SKILL.md"
                skill_md = nested if nested.is_file() else None
                if skill_md is None:
                    continue
            try:
                fm = self._parse_frontmatter(skill_md.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                logger.warning("读取 SKILL.md 失败 %s: %s", skill_md, e)
                continue
            rid = fm.get("name") or skill_dir.name
            self.skills[rid] = SkillManifest(
                id=rid,
                name=fm.get("name", rid),
                description=fm.get("description", ""),
                type=fm.get("type", "tool"),
                version=str(fm.get("version", "0.0.0")),
                requires=[str(x) for x in (fm.get("requires") or [])],
                path=str(skill_md),
            )

    # ── scenes ────────────────────────────────────────────────────

    def _scan_scenes(self):
        scenes_dir = Path(self.agent_loop_dir) / "scenes"
        if not scenes_dir.is_dir():
            return
        for scene_md in sorted(scenes_dir.glob("*.md")):
            if scene_md.name == "_template.md":
                continue
            try:
                text = scene_md.read_text(encoding="utf-8")
                fm = self._parse_frontmatter(text)
            except Exception as e:  # noqa: BLE001
                logger.warning("读取 scene 失败 %s: %s", scene_md, e)
                continue
            rid = fm.get("name") or scene_md.stem
            dev_server = None
            # 从正文提取 dev_server yaml 块（如有）
            m = text.find("dev_server:")
            if m != -1:
                block = text[m:m + 400].split("\n---")[0]
                try:
                    dev_server = yaml.safe_load(block) or None
                except Exception:  # noqa: BLE001
                    dev_server = None
            self.scenes[rid] = SceneManifest(
                id=rid,
                name=fm.get("name", rid),
                type=fm.get("type", "backend"),
                description=fm.get("description", ""),
                dev_server=dev_server,
                path=str(scene_md),
            )

    # ── agents ────────────────────────────────────────────────────

    def _scan_agents(self):
        agents_dir = Path(self.agent_loop_dir) / "agents"
        if not agents_dir.is_dir():
            return
        for agent_md in sorted(agents_dir.glob("*.md")):
            try:
                fm = self._parse_frontmatter(agent_md.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                logger.warning("读取 agent 失败 %s: %s", agent_md, e)
                continue
            rid = fm.get("name") or agent_md.stem
            tools = [str(x) for x in (fm.get("tools") or "").split(",")] if isinstance(fm.get("tools"), str) \
                else [str(x) for x in (fm.get("tools") or [])]
            self.agents[rid] = AgentManifest(
                id=rid,
                name=fm.get("name", rid),
                description=fm.get("description", ""),
                tools=tools,
                permission_mode=fm.get("permissionMode", fm.get("permission_mode", "default")),
                path=str(agent_md),
            )

    # ── 查询接口 ──────────────────────────────────────────────────

    def get_skill(self, key: str) -> Optional[SkillManifest]:
        self.load()
        return self.skills.get(key)

    def get_scene(self, key: str) -> Optional[SceneManifest]:
        self.load()
        return self.scenes.get(key)

    def get_agent(self, key: str) -> Optional[AgentManifest]:
        self.load()
        return self.agents.get(key)

    def list_skills(self) -> list[SkillManifest]:
        self.load()
        return list(self.skills.values())

    def list_scenes(self) -> list[SceneManifest]:
        self.load()
        return list(self.scenes.values())

    def list_agents(self) -> list[AgentManifest]:
        self.load()
        return list(self.agents.values())

    def skills_summary(self) -> str:
        """生成注入 Planner 上下文的可读技能清单。"""
        self.load()
        if not self.skills:
            return "（无可用技能）"
        lines = ["可用技能清单（按需选用，不强制全部加载）："]
        for s in self.skills.values():
            req = f" [requires: {', '.join(s.requires)}]" if s.requires else ""
            lines.append(f"- `{s.name}` ({s.type}, v{s.version}) — {s.description}{req}")
        return "\n".join(lines)


def load_registry(project_root: str) -> AssetRegistry:
    """工厂函数：创建并加载注册表。"""
    reg = AssetRegistry(project_root)
    reg.load()
    return reg


def default_registry() -> AssetRegistry:
    """加载 Orbit 项目根（backend 上层 3 级）的注册表。

    与 orchestrator._AGENTS_ROOT 的定位逻辑保持一致：
    backend/app/agents/ → Orbit 根需要 3 层 ..。
    """
    root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return load_registry(root)

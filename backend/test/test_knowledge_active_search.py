"""检索链路与 active index / 语义缓存的租户隔离回归。

重点验证多租户改造后的读取语义：
- 已登录成员一次检索会同时覆盖「组织共享库 ∪ 本人私有库」
- 匿名只读匿名沙箱，且**绝不**落到全局 `documents` 库
"""
from app import search as search_module
from app import cache as cache_module
from app.config import settings
from app.knowledge_agent.releases import ActiveIndexVersion
from app.multitenant import TenantScope

TENANT_A = "org_active_a"


def _shared(user_id=7):
    return TenantScope(TENANT_A, user_id, "shared")


def _personal(user_id=7):
    return TenantScope(TENANT_A, user_id, "personal")


class FakeCollection:
    def __init__(self, name=None):
        self.name = name

    def count(self):
        return 1

    def query(self, **kwargs):
        return {
            "ids": [["chunk-1"]],
            "documents": [["support target is four hours"]],
            "metadatas": [[{"source_path": "clean-policy.md"}]],
            "distances": [[0.1]],
        }


def _patch_active(monkeypatch, requested, name_for=None):
    """把 get_active_index 换成按 scope 解析 collection 的假实现。"""
    def fake_get_active_index(**kwargs):
        scope = kwargs["scope"]
        name = name_for(scope) if name_for else f"kr_{scope.scope}"
        return ActiveIndexVersion(
            run_id="run-1", collection_name=name, generation=2, legacy=False,
        )

    monkeypatch.setattr(search_module, "get_active_index", fake_get_active_index)
    monkeypatch.setattr(
        search_module,
        "get_collection_by_name",
        lambda name: requested.append(name) or FakeCollection(name),
    )
    monkeypatch.setattr(search_module, "encode", lambda texts: [[0.1, 0.2]])
    monkeypatch.setattr(search_module, "_knowledge_database_path", lambda: object())


def test_search_covers_shared_and_personal_scopes(monkeypatch):
    """一次检索必须同时打组织共享库与本人私有库（产品语义）。"""
    requested = []
    _patch_active(monkeypatch, requested)

    results = search_module.search("support target", scope=_shared())

    # shared 与 personal 两个作用域都被检索到
    assert requested == ["kr_shared", "kr_personal"]
    assert results[0]["metadata"]["source_path"] == "clean-policy.md"
    assert "clean-policy.md" in search_module.search_formatted(
        "support target", scope=_shared()
    )


def test_search_result_is_tagged_with_source_scope(monkeypatch):
    """检索结果标注来源作用域，前端可区分「组织文档 / 我的文档」。"""
    requested = []
    _patch_active(monkeypatch, requested)

    results = search_module.search("support target", scope=_shared())

    assert results[0]["metadata"]["scope"] == "shared"
    assert results[0]["metadata"]["collection"] == "kr_shared"


def test_legacy_fallback_uses_scope_collection_not_global(monkeypatch):
    """没有 active index 时回退到**该作用域**的默认库，绝不落到全局库。

    回归：旧实现回退到 `settings.CHROMA_COLLECTION`（`documents`），
    所有未登录访客共享同一个空间。
    """
    requested = []
    _patch_active(
        monkeypatch, requested, name_for=lambda scope: scope.collection
    )

    search_module.search("legacy", scope=_shared())

    assert requested[0] == "t_org_active_a"
    assert requested[1].startswith("p_")
    assert settings.CHROMA_COLLECTION not in requested
    assert settings.ANON_COLLECTION not in requested


def test_anonymous_search_stays_in_anon_sandbox(monkeypatch):
    """匿名检索只打匿名沙箱，且沙箱名不等于全局库。"""
    requested = []
    _patch_active(monkeypatch, requested, name_for=lambda scope: scope.collection)

    search_module.search("legacy", scope=TenantScope())

    assert requested == [settings.ANON_COLLECTION]
    assert settings.ANON_COLLECTION != settings.CHROMA_COLLECTION


def test_semantic_answer_cache_is_partitioned_by_namespace(monkeypatch):
    """语义缓存按命名空间隔离：不同租户/版本互不可见。"""
    cache_module.clear()
    monkeypatch.setattr(cache_module, "encode", lambda texts: [[1.0, 0.0]])
    cache_module.put(
        "same question", "old answer", [], "test",
        namespace="t:org_a:u:7|kr_old",
    )

    assert cache_module.get("same question", namespace="t:org_a:u:7|kr_new") is None
    assert cache_module.get(
        "same question", namespace="t:org_a:u:7|kr_old"
    )["answer"] == "old answer"


def test_purge_prefix_clears_only_matching_tenant_ids(monkeypatch):
    """组织共享库变更后按租户前缀清缓存，不能误伤其他组织。"""
    cache_module.clear()
    monkeypatch.setattr(cache_module, "encode", lambda texts: [[1.0, 0.0]])
    cache_module.put("q1", "a1", [], "m", namespace="t:org_a:u:7|col")
    cache_module.put("q2", "a2", [], "m", namespace="t:org_a:u:8|col")
    cache_module.put("q3", "a3", [], "m", namespace="t:org_b:u:9|col")

    assert cache_module.purge_prefix(TenantScope("org_a", 7).tenant_prefix) == 2
    assert cache_module.get("q1", namespace="t:org_a:u:7|col") is None
    assert cache_module.get("q3", namespace="t:org_b:u:9|col") is not None


def test_purge_personal_prefix_does_not_touch_other_member(monkeypatch):
    """个人私有库变更只清本人缓存，同组织其他成员不受影响。"""
    cache_module.clear()
    monkeypatch.setattr(cache_module, "encode", lambda texts: [[1.0, 0.0]])
    # 命名空间一律由 TenantScope 派生，避免与 TENANT_A 字面量脱节
    ns_7 = f"{_personal(7).read_key}|col"
    ns_8 = f"{_personal(8).read_key}|col"
    cache_module.put("q1", "a1", [], "m", namespace=ns_7)
    cache_module.put("q2", "a2", [], "m", namespace=ns_8)

    assert cache_module.purge_prefix(f"{_personal(7).read_key}|") == 1
    assert cache_module.get("q1", namespace=ns_7) is None
    assert cache_module.get("q2", namespace=ns_8) is not None

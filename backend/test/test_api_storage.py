"""api/storage.py — 混合存储接口测试 /api/storage/*"""


def test_strategies(client):
    r = client.get("/api/storage/strategies")
    assert r.status_code == 200
    data = r.json()
    assert "strategies" in data
    assert "file_routing" in data
    assert data["total_strategies"] == 5


def test_analyze_markdown(client):
    r = client.post("/api/storage/analyze", json={"filename": "手册.md", "text": "# 产品介绍\n使用说明", "file_size": 100})
    assert r.status_code == 200
    data = r.json()
    assert data["strategy"] == "rag"
    assert data["content_type"] == "document"


def test_analyze_contract(client):
    r = client.post("/api/storage/analyze", json={
        "filename": "合同.pdf", "text": "甲方与乙方签署本合同，盖章生效", "file_size": 2048,
    })
    data = r.json()
    assert data["strategy"] == "original"
    assert data["file_size"] == 2048


def test_analyze_csv(client):
    r = client.post("/api/storage/analyze", json={"filename": "data.csv", "text": "a,b\n1,2"})
    assert r.json()["strategy"] == "structured"


def test_analyze_missing_filename(client):
    r = client.post("/api/storage/analyze", json={"text": "内容"})
    assert r.status_code == 400
    assert "文件名不能为空" in r.json()["detail"]

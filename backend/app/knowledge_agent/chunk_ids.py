import hashlib


def make_chunk_id(
    *,
    run_id: str,
    source_hash: str,
    strategy_id: str,
    chunk_index: int,
    locator: str,
) -> str:
    """Return a stable ID for a chunk at one source locator."""

    payload = "\0".join(
        [run_id, source_hash, strategy_id, str(chunk_index), locator]
    ).encode("utf-8")
    return "kc_" + hashlib.sha256(payload).hexdigest()[:40]

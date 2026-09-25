"""运维 CLI：用户角色管理（RBAC 引导路径）。

在没有图形化后台的前提下，需要一个受支持的方式把某个账号提升为 admin，
否则 pause-all 这类管理接口将永远无人可调。

用法（在 backend/ 目录下）：
    python -m app.admin_cli list
    python -m app.admin_cli promote <username>
    python -m app.admin_cli demote <username>

注意：角色变更立即生效（require_role 每次请求回查数据库），
无需用户重新登录；但已签发的 Token 里的 role 声明仍是旧值，
因此不要在业务代码里直接信任 Token 的 role 字段。
"""

import argparse
import sys

from .multitenant import init_db, _get_db

VALID_ROLES = ("user", "admin")


def _cmd_list() -> int:
    init_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, role, tenant_id, created_at FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("（暂无用户）")
        return 0
    print(f"{'ID':<6}{'USERNAME':<28}{'ROLE':<10}{'TENANT':<16}CREATED")
    for r in rows:
        print(f"{r['id']:<6}{r['username']:<28}{r['role'] or '-':<10}"
              f"{r['tenant_id'] or '-':<16}{r['created_at'] or '-'}")
    return 0


def _set_role(username: str, role: str) -> int:
    init_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            print(f"错误：用户不存在: {username}", file=sys.stderr)
            return 1
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, row["id"]))
        conn.commit()
        print(f"OK: {username} (id={row['id']}) → role={role}")
        return 0
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin_cli", description="Orbit 用户角色管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出全部用户及其角色")

    p_promote = sub.add_parser("promote", help="把用户提升为 admin")
    p_promote.add_argument("username")

    p_demote = sub.add_parser("demote", help="把用户降为普通 user")
    p_demote.add_argument("username")

    args = parser.parse_args(argv)

    if args.command == "list":
        return _cmd_list()
    if args.command == "promote":
        return _set_role(args.username, "admin")
    if args.command == "demote":
        return _set_role(args.username, "user")
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

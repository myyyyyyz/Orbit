"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Building2, Users, Ticket, Copy, Check, RefreshCw, Loader2, LogIn, ShieldCheck,
} from "lucide-react";
import { tenants, auth, type TenantMember, type TenantSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const ROLE_LABELS: Record<string, string> = {
  owner: "拥有者",
  admin: "管理员",
  member: "成员",
};

function roleLabel(role?: string | null) {
  if (!role) return "—";
  return ROLE_LABELS[role] || role;
}

/**
 * 组织（租户）设置面板。
 *
 * 权限与后端一一对应：改名 / 轮换邀请码需 owner|admin，调整成员角色仅 owner。
 * 「加入其他组织」对任何登录用户开放——用邀请码切换租户归属，
 * 后端会换发令牌，这里负责把新会话写回本地。
 *
 * busy 用单个 key 表示（"name" | "rotate" | "join" | `member:${id}`），
 * 避免多个布尔互相打架。
 */
export function TenantPanel() {
  const { isAuthenticated, username, login } = useAuth();

  const [summary, setSummary] = useState<TenantSummary | null>(null);
  const [members, setMembers] = useState<TenantMember[]>([]);
  // loaded 只在「异步拉取完成」时置位；loading 由它派生，
  // 避免在 effect 体内同步 setState（react-hooks/set-state-in-effect）。
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [nameDraft, setNameDraft] = useState("");
  const [copied, setCopied] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const myRole = summary?.my_role;
  const canManage = myRole === "owner" || myRole === "admin";
  const isOwner = myRole === "owner";
  const loading = isAuthenticated && !loaded;

  const refresh = useCallback(async () => {
    if (!isAuthenticated) return;
    const [s, m] = await Promise.all([tenants.me(), tenants.members()]);
    setSummary(s);
    setNameDraft(s.name || "");
    setMembers(m.members);
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    void (async () => {
      try {
        const [s, m] = await Promise.all([tenants.me(), tenants.members()]);
        if (cancelled) return;
        setSummary(s);
        setNameDraft(s.name || "");
        setMembers(m.members);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载组织信息失败");
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated]);

  /** 统一的操作包装：清提示 → 置忙 → 执行 → 复位。 */
  const run = async (key: string, fn: () => Promise<void>) => {
    setError(""); setNotice("");
    setBusy(key);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(null);
    }
  };

  const handleRename = () => {
    const next = nameDraft.trim();
    if (!next || next === summary?.name) return;
    void run("name", async () => {
      await tenants.rename(next);
      await refresh();
      setNotice("组织名称已更新");
    });
  };

  const handleRotate = () => {
    if (!window.confirm("重置后旧邀请码立即失效，已发出的邀请将无法使用。确定继续？")) return;
    void run("rotate", async () => {
      const res = await tenants.rotateInviteCode();
      setSummary((prev) => (prev ? { ...prev, invite_code: res.invite_code } : prev));
      setNotice("邀请码已重置");
    });
  };

  const handleCopy = async () => {
    const code = summary?.invite_code;
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("复制失败，请手动选择文本复制");
    }
  };

  const handleMemberRole = (member: TenantMember, role: string) => {
    if (role === member.tenant_role) return;
    void run(`member:${member.id}`, async () => {
      await tenants.updateMemberRole(member.id, role);
      await refresh();
      setNotice(`已将 ${member.username} 调整为「${roleLabel(role)}」`);
    });
  };

  const handleJoin = () => {
    const code = joinCode.trim();
    if (!code) return;
    void run("join", async () => {
      const res = await auth.join(code);
      // 后端已换发令牌：旧 Token 的 tenant_id 是加入前组织的快照，必须整体替换
      login(username || res.username || "", res.access_token, res.refresh_token, res.role, {
        id: res.tenant_id,
        name: res.tenant_name,
        role: res.tenant_role,
        invite_code: res.invite_code,
        collections: res.collections,
      });
      setJoinCode("");
      await refresh();
      setNotice("已加入组织，令牌已刷新");
    });
  };

  if (!isAuthenticated) {
    return (
      <section>
        <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
          <Building2 className="h-4 w-4 text-muted" />
          组织与成员
        </h3>
        <div className="rounded-xl border border-border bg-surface/50 p-4 text-xs text-muted">
          登录后可以创建/加入组织，并在组织内共享知识库。
        </div>
      </section>
    );
  }

  return (
    <section>
      <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
        <Building2 className="h-4 w-4 text-muted" />
        组织与成员
        {myRole && (
          <span className="text-[10px] bg-primary/15 text-primary px-1.5 py-0.5 rounded-full">
            {roleLabel(myRole)}
          </span>
        )}
      </h3>

      <div className="rounded-xl border border-border bg-surface/50 p-4 space-y-4">
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-muted py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
          </div>
        ) : !summary ? (
          <div className="text-xs text-error py-1">{error || "无法获取组织信息"}</div>
        ) : (
          <>
            {/* 组织名（owner/admin 可改） */}
            <div>
              <label className="block text-xs font-medium text-muted mb-1">组织名称</label>
              {canManage ? (
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-xs
                               focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                  <button
                    type="button"
                    onClick={handleRename}
                    disabled={busy === "name" || !nameDraft.trim() || nameDraft.trim() === summary.name}
                    className="shrink-0 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground
                               hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {busy === "name" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "保存"}
                  </button>
                </div>
              ) : (
                <div className="text-sm">{summary.name}</div>
              )}
            </div>

            {/* 概览 */}
            <div className="grid grid-cols-2 gap-2 text-center">
              <div className="rounded-lg bg-surface p-2">
                <div className="text-base font-semibold">{summary.member_count}</div>
                <div className="text-[10px] text-muted mt-0.5">成员数</div>
              </div>
              <div className="rounded-lg bg-surface p-2">
                <div className="text-base font-semibold">{summary.plan || "free"}</div>
                <div className="text-[10px] text-muted mt-0.5">套餐</div>
              </div>
            </div>

            {/* 邀请码（owner/admin 可见） */}
            <div>
              <label className="flex items-center gap-1.5 text-xs font-medium text-muted mb-1">
                <Ticket className="h-3.5 w-3.5" />
                邀请码
              </label>
              {canManage ? (
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-lg border border-border bg-surface px-3 py-2 text-xs tracking-wider">
                    {summary.invite_code || "—"}
                  </code>
                  <button
                    type="button"
                    onClick={handleCopy}
                    title="复制"
                    className="shrink-0 rounded-lg border border-border p-2 text-muted hover:text-foreground hover:border-border-strong"
                  >
                    {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
                  </button>
                  <button
                    type="button"
                    onClick={handleRotate}
                    disabled={busy === "rotate"}
                    title="重置邀请码"
                    className="shrink-0 rounded-lg border border-border p-2 text-muted hover:text-error hover:border-error/40 disabled:opacity-50"
                  >
                    {busy === "rotate" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                  </button>
                </div>
              ) : (
                <p className="text-[11px] text-muted/70">仅拥有者/管理员可见。</p>
              )}
              <p className="mt-1 text-[10px] text-muted/50">
                把邀请码给同事，对方在注册页填写即可加入本组织并共享知识库。
              </p>
            </div>

            {/* 成员列表 */}
            <div>
              <label className="flex items-center gap-1.5 text-xs font-medium text-muted mb-2">
                <Users className="h-3.5 w-3.5" />
                成员（{members.length}）
              </label>
              <div className="space-y-1.5">
                {members.map((m) => (
                  <div
                    key={m.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-surface/60 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">{m.username}</div>
                      <div className="text-[10px] text-muted/60">#{m.id} · {roleLabel(m.tenant_role)}</div>
                    </div>
                    {isOwner ? (
                      <select
                        value={m.tenant_role}
                        disabled={busy === `member:${m.id}`}
                        onChange={(e) => handleMemberRole(m, e.target.value)}
                        className="shrink-0 rounded-md border border-border bg-surface px-2 py-1 text-[11px]"
                      >
                        {["owner", "admin", "member"].map((r) => (
                          <option key={r} value={r}>{roleLabel(r)}</option>
                        ))}
                      </select>
                    ) : (
                      <span className="shrink-0 text-[10px] text-muted/60">{roleLabel(m.tenant_role)}</span>
                    )}
                  </div>
                ))}
              </div>
              {isOwner && (
                <p className="mt-1.5 flex items-center gap-1 text-[10px] text-muted/50">
                  <ShieldCheck className="h-3 w-3" />
                  最后一个拥有者不可被降级。
                </p>
              )}
            </div>

            {/* 加入其他组织 */}
            <div className="border-t border-border/50 pt-3">
              <label className="flex items-center gap-1.5 text-xs font-medium text-muted mb-1">
                <LogIn className="h-3.5 w-3.5" />
                用邀请码加入其他组织
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value)}
                  placeholder="输入邀请码"
                  className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-xs
                             placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <button
                  type="button"
                  onClick={handleJoin}
                  disabled={busy === "join" || !joinCode.trim()}
                  className="shrink-0 rounded-lg border border-border bg-surface px-3 py-2 text-xs
                             hover:border-border-strong disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {busy === "join" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "加入"}
                </button>
              </div>
              <p className="mt-1 text-[10px] text-muted/50">
                切换组织会替换你的租户归属；原组织的私有文档不会被带走。
              </p>
            </div>

            {(notice || error) && (
              <p className={cn("text-[11px]", error ? "text-error" : "text-success")}>
                {error || notice}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

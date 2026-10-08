"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  Upload, FileText, Search, Trash2, Loader2, CheckCircle2, AlertCircle,
  Building2, Lock,
} from "lucide-react";
import { cn, formatSize } from "@/lib/utils";
import { knowledge, type KnowledgeScope } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { KnowledgeWorkbench } from "@/components/knowledge-workbench/knowledge-workbench";

interface DocRecord {
  filename: string;
  status: string;
  size?: number;
  uploadedAt?: string;
}

export function KnowledgeBasePanel() {
  const [view, setView] = useState<"workbench" | "legacy">("workbench");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-end gap-1 border-b border-border/50 bg-[#0b1324] px-4 py-2">
        <button
          type="button"
          onClick={() => setView("workbench")}
          className={cn("rounded-lg px-3 py-1.5 text-xs", view === "workbench" ? "bg-primary text-white" : "text-muted hover:bg-surface")}
        >
          RAG Workbench
        </button>
        <button
          type="button"
          onClick={() => setView("legacy")}
          className={cn("rounded-lg px-3 py-1.5 text-xs", view === "legacy" ? "bg-primary text-white" : "text-muted hover:bg-surface")}
        >
          旧版上传
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {view === "workbench" ? <KnowledgeWorkbench /> : <LegacyKnowledgeBasePanel />}
      </div>
    </div>
  );
}

function LegacyKnowledgeBasePanel() {
  const { isAuthenticated } = useAuth();
  // 空间选择：组织共享 / 仅我的。匿名会话没有个人空间，一律落匿名沙箱。
  const [scopeChoice, setScopeChoice] = useState<KnowledgeScope>("shared");
  const scope: KnowledgeScope = isAuthenticated ? scopeChoice : "shared";

  const [documents, setDocuments] = useState<DocRecord[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<"idle" | "success" | "error">("idle");
  const [searchQuery, setSearchQuery] = useState("");
  const [backendError, setBackendError] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch existing documents on mount / space switch
  useEffect(() => {
    let cancelled = false;
    knowledge.search("", 50, scope).then((data) => {
      if (cancelled) return;
      if (data.results) {
        const seen = new Set<string>();
        const docs: DocRecord[] = [];
        for (const r of data.results) {
          const fn = r.metadata?.source || "unknown";
          if (!seen.has(fn)) {
            seen.add(fn);
            docs.push({ filename: fn, status: "indexed" });
          }
        }
        setDocuments(docs);
      }
    }).catch(() => { if (!cancelled) setBackendError(true); });
    return () => { cancelled = true; };
  }, [scope]);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadStatus("idle");

    try {
      const res = await knowledge.upload(file, scope);
      setDocuments((prev) => [
        { filename: res.filename, status: res.status, size: file.size, uploadedAt: new Date().toLocaleString() },
        ...prev.filter((d) => d.filename !== res.filename),
      ]);
      setUploadStatus("success");
    } catch {
      setUploadStatus("error");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [scope]);

  const handleDelete = useCallback((filename: string) => {
    setDocuments((prev) => prev.filter((d) => d.filename !== filename));
    // 后端按 source 元数据删除该文档的全部 chunk（必须指定其所在空间）
    knowledge.deleteSource(filename, scope).catch(() => {
      /* best-effort：失败不阻塞 UI，刷新后可见真实状态 */
    });
  }, [scope]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <h2 className="text-base font-semibold tracking-tight">知识库管理</h2>
        <p className="mt-1 text-xs text-muted">上传文档，让 AI 检索你的专属知识</p>
        {backendError && (
          <p className="mt-2 text-xs text-warning">后端服务未运行，部分功能不可用</p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
        {/* 空间选择：组织共享 / 仅我的 */}
        <div>
          <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-surface/40 p-1">
            {([
              { key: "shared" as const, label: "组织共享", icon: <Building2 className="h-3.5 w-3.5" /> },
              { key: "personal" as const, label: "仅我的", icon: <Lock className="h-3.5 w-3.5" /> },
            ]).map(({ key, label, icon }) => {
              const active = scope === key;
              const disabled = key === "personal" && !isAuthenticated;
              return (
                <button
                  key={key}
                  type="button"
                  disabled={disabled}
                  onClick={() => setScopeChoice(key)}
                  className={cn(
                    "flex items-center justify-center gap-1.5 rounded-md py-1.5 text-xs transition-colors",
                    active ? "bg-primary text-white" : "text-muted hover:bg-surface",
                    disabled && "cursor-not-allowed opacity-40 hover:bg-transparent"
                  )}
                >
                  {icon}
                  {label}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[11px] text-muted/60">
            {isAuthenticated
              ? (scope === "shared"
                  ? "上传与删除作用于「组织共享库」，同组织成员都可以检索到。"
                  : "上传与删除只作用于「我的私有库」，仅你本人可检索。")
              : "未登录：使用匿名空间。登录后可使用组织共享库与个人私有库。"}
          </p>
        </div>

        {/* Upload Area */}
        <div>
          <div
            onClick={() => fileInputRef.current?.click()}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8",
              "transition-all duration-200",
              uploadStatus === "success"
                ? "border-success/30 bg-success/5"
                : uploadStatus === "error"
                ? "border-error/30 bg-error/5"
                : "border-border hover:border-primary/30 hover:bg-primary/5"
            )}
          >
            {uploading ? (
              <>
                <Loader2 className="h-8 w-8 text-primary animate-spin" />
                <p className="mt-3 text-sm text-muted">上传中...</p>
              </>
            ) : uploadStatus === "success" ? (
              <>
                <CheckCircle2 className="h-8 w-8 text-success" />
                <p className="mt-3 text-sm text-success">上传成功</p>
              </>
            ) : uploadStatus === "error" ? (
              <>
                <AlertCircle className="h-8 w-8 text-error" />
                <p className="mt-3 text-sm text-error">上传失败，请重试</p>
              </>
            ) : (
              <>
                <Upload className="h-8 w-8 text-muted" />
                <p className="mt-3 text-sm text-muted">拖拽文件到此处，或点击上传</p>
                <p className="mt-1 text-xs text-muted/60">支持 PDF、Markdown、TXT</p>
              </>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.md,.txt,.png,.jpg,.jpeg"
              onChange={handleUpload}
              className="hidden"
            />
          </div>
        </div>

        {/* Search */}
        <div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/50" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索知识库..."
              className="w-full rounded-lg border border-border bg-surface py-2 pl-9 pr-3 text-sm
                         placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                         transition-[border-color,box-shadow] duration-200"
            />
          </div>
        </div>

        {/* Document List */}
        <div>
          <p className="text-xs font-medium text-muted/70 mb-2 uppercase tracking-wider">
            已索引文档 ({documents.length})
          </p>
          {documents.length === 0 ? (
            <div className="rounded-lg border border-border/50 bg-surface/30 px-4 py-8 text-center">
              <FileText className="mx-auto h-6 w-6 text-muted/40" />
              <p className="mt-2 text-sm text-muted">暂无文档</p>
              <p className="mt-0.5 text-xs text-muted/60">上传第一个文档开始使用</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {documents
                .filter((d) =>
                  d.filename.toLowerCase().includes(searchQuery.toLowerCase())
                )
                .map((doc) => (
                  <div
                    key={doc.filename}
                    className="flex items-center gap-3 rounded-lg border border-border/50 bg-surface/50 px-3.5 py-2.5
                               group hover:border-primary/20 transition-colors duration-150"
                  >
                    <FileText className="h-4 w-4 shrink-0 text-muted" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{doc.filename}</p>
                      <p className="text-[11px] text-muted/60">
                        {formatSize(doc.size)} · {doc.uploadedAt}
                      </p>
                    </div>
                    <button
                      onClick={() => handleDelete(doc.filename)}
                      className="rounded-md p-1.5 text-muted/40 opacity-0 group-hover:opacity-100
                                 hover:text-error hover:bg-error/10 transition-all duration-150 cursor-pointer"
                      title="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { Upload, FileText, Search, Trash2, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { cn, formatSize } from "@/lib/utils";
import { knowledge } from "@/lib/api";

interface DocRecord {
  filename: string;
  status: string;
  size?: number;
  uploadedAt?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export function KnowledgeBasePanel() {
  const [documents, setDocuments] = useState<DocRecord[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<"idle" | "success" | "error">("idle");
  const [searchQuery, setSearchQuery] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch existing documents on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/knowledge/search?q=&top_k=50`)
      .then((r) => r.json())
      .then((data) => {
        if (data.results) {
          const seen = new Set<string>();
          const docs: DocRecord[] = [];
          for (const r of data.results) {
            const fn = r.metadata?.filename || "unknown";
            if (!seen.has(fn)) {
              seen.add(fn);
              docs.push({ filename: fn, status: "indexed" });
            }
          }
          setDocuments(docs);
        }
      })
      .catch(() => {/* backend may not support list */});
  }, []);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadStatus("idle");

    try {
      const res = await knowledge.upload(file);
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
  }, []);

  const handleDelete = useCallback((filename: string) => {
    setDocuments((prev) => prev.filter((d) => d.filename !== filename));
    // Attempt backend delete (best-effort)
    fetch(`${API_BASE}/api/knowledge/delete?filename=${encodeURIComponent(filename)}`, { method: "DELETE" })
      .catch(() => {/* may not be supported */});
  }, []);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <h2 className="text-base font-semibold tracking-tight">知识库管理</h2>
        <p className="mt-1 text-xs text-muted">上传文档，让 AI 检索你的专属知识</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
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

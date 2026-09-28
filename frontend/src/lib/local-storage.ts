import { useCallback, useSyncExternalStore } from "react";

// ─────────────────────────────────────────────────────────────
// localStorage 的 React 化读取
//
// 历史写法是「useEffect 里读 localStorage → setState」，在 React Compiler
// 的 react-hooks/set-state-in-effect 规则下属于违规（effect 内同步 setState
// 会引发级联渲染），而且把「外部数据源」硬塞进组件 state，既要手写 mounted
// 标志防 hydration 不一致，又会在令牌被 api 层刷新后失同步。
//
// 正确做法：localStorage 是 React 之外的外部存储，用 useSyncExternalStore
// 订阅。服务端渲染走 getServerSnapshot（返回默认值），hydration 后再切到
// 真实值，天然无 mismatch，也不需要额外的 mounted state。
//
// 同标签页写入不会触发原生 storage 事件（它只在跨标签页时触发），所以
// 所有写入统一走 setLocalValue/removeLocalValue，由它们主动通知订阅者。
// api.ts 里直接写令牌的地方也必须调用 notifyLocalChange()。
// ─────────────────────────────────────────────────────────────

const listeners = new Set<() => void>();

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  // 原生 storage 事件：跨标签页同步（如另一个标签页登出）
  if (typeof window !== "undefined") {
    window.addEventListener("storage", onStoreChange);
  }
  return () => {
    listeners.delete(onStoreChange);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", onStoreChange);
    }
  };
}

/** 通知所有订阅者：本地存储已变化。写入 localStorage 后必须调用。 */
export function notifyLocalChange(): void {
  listeners.forEach((listener) => listener());
}

/** 写入并通知；传 null 等价于删除。 */
export function setLocalValue(key: string, value: string | null): void {
  if (typeof window === "undefined") return;
  if (value === null) localStorage.removeItem(key);
  else localStorage.setItem(key, value);
  notifyLocalChange();
}

/** 删除并通知。 */
export function removeLocalValue(key: string): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(key);
  notifyLocalChange();
}

/**
 * 订阅 localStorage 中的字符串值。
 * SSR 与 hydration 首帧返回 null，挂载后自动切换为真实值。
 */
export function useLocalString(key: string): string | null {
  const getSnapshot = useCallback(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(key);
  }, [key]);
  return useSyncExternalStore(subscribe, getSnapshot, () => null);
}

/** 订阅 localStorage 中的布尔标记（值为字符串 "true" 时为真）。 */
export function useLocalFlag(key: string): boolean {
  const getSnapshot = useCallback(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(key) === "true";
  }, [key]);
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}

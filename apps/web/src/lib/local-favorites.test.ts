import { describe, expect, it, beforeEach } from "vitest";
import {
  loadLocalFavorites, isLocalFavorite, toggleLocalFavorite, removeLocalFavorite,
} from "./local-favorites";

// vitest node 环境无 localStorage：轻量 mock
const store = new Map<string, string>();
beforeEach(() => store.clear());
(globalThis as unknown as { localStorage: unknown }).localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, String(v)); },
  removeItem: (k: string) => { store.delete(k); },
};

describe("local favorites（未登录收藏）", () => {
  it("初始为空", () => {
    expect(loadLocalFavorites()).toEqual([]);
    expect(isLocalFavorite("https://x.com/a")).toBe(false);
  });

  it("toggle 添加后返回 true 并可读回", () => {
    const now = toggleLocalFavorite("https://x.com/a", "标题A");
    expect(now).toBe(true);
    expect(isLocalFavorite("https://x.com/a")).toBe(true);
    const list = loadLocalFavorites();
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ url: "https://x.com/a", title: "标题A", kind: "article" });
    expect(list[0]!.id).toBe("https://x.com/a");
  });

  it("再次 toggle 取消并持久化删除", () => {
    toggleLocalFavorite("https://x.com/a", "A");
    const now = toggleLocalFavorite("https://x.com/a", "A");
    expect(now).toBe(false);
    expect(isLocalFavorite("https://x.com/a")).toBe(false);
    expect(loadLocalFavorites()).toEqual([]);
  });

  it("多个收藏互不影响", () => {
    toggleLocalFavorite("https://x.com/a", "A");
    toggleLocalFavorite("https://x.com/b", "B");
    expect(loadLocalFavorites()).toHaveLength(2);
    removeLocalFavorite("https://x.com/a");
    expect(isLocalFavorite("https://x.com/a")).toBe(false);
    expect(isLocalFavorite("https://x.com/b")).toBe(true);
  });

  it("脏数据容错：非数组/坏项直接忽略", () => {
    store.set("kaogong.localFavs", JSON.stringify({ bad: true }));
    expect(loadLocalFavorites()).toEqual([]);
    store.set("kaogong.localFavs", JSON.stringify([{ title: "无url" }, "str", null]));
    expect(loadLocalFavorites()).toEqual([]);
  });
});

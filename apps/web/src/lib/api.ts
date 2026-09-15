// 类型化 API 客户端：自动带 X-Device-Id 头，响应类型来自 @kaogong/contracts。
import type {
  AccountExport,
  ApiError,
  AuthResponse,
  AuthUser,
  EmailCodeRequest,
  EmailCodeVerify,
  ExplainResponse,
  Favorite,
  FavoriteCreate,
  InviteStatus,
  NotificationSettings,
  NotificationSettingsUpdate,
  PracticeRecord,
  PracticeSubmit,
  Profile,
  ProfileUpdate,
  ReviewGrade,
  ReviewGradeResponse,
  ReviewStateResponse,
  Subscription,
  SubscriptionResponse,
  TermAskRequest,
  TermAskResponse,
  WrongQuestion,
} from "@kaogong/contracts";
import { getDeviceId } from "./device";

export interface Envelope<T> {
  ok: boolean;
  data: T | null;
  error?: ApiError;
}

/** 后端地址：本地 wrangler dev 默认 8787；部署时用 PUBLIC_API_BASE 环境变量覆盖 */
export const API_BASE =
  (import.meta.env.PUBLIC_API_BASE as string | undefined) ?? "http://127.0.0.1:8787";

if (import.meta.env.PROD && !import.meta.env.PUBLIC_API_BASE) {
  console.error("[kaogong] 生产构建未设置 PUBLIC_API_BASE，前端将回退到 127.0.0.1:8787");
}

export function createApi(base: string, deviceId: () => string) {
  async function request<T>(path: string, init?: RequestInit): Promise<Envelope<T>> {
    const headers = new Headers(init?.headers);
    headers.set("x-device-id", deviceId());
    if (init?.body) headers.set("content-type", "application/json");
    try {
      const res = await fetch(base + path, { ...init, headers, credentials: "include" });
      return (await res.json()) as Envelope<T>;
    } catch {
      return { ok: false, data: null, error: { code: "NETWORK", message: "网络错误" } };
    }
  }

  return {
    listFavorites: (url?: string) =>
      request<Favorite[]>(url ? `/api/favorites?url=${encodeURIComponent(url)}` : "/api/favorites"),
    addFavorite: (body: FavoriteCreate) =>
      request<Favorite>("/api/favorites", { method: "POST", body: JSON.stringify(body) }),
    removeFavorite: (id: string) => request<null>(`/api/favorites/${id}`, { method: "DELETE" }),
    submitPractice: (body: PracticeSubmit) =>
      request<PracticeRecord>("/api/practice", { method: "POST", body: JSON.stringify(body) }),
    listWrongQuestions: () => request<WrongQuestion[]>("/api/practice/wrong"),
    /** 已掌握：点过「掌握 ✓」的题。服务端软删除（2026-09-15 起），换设备也还在。 */
    listMasteredQuestions: () => request<WrongQuestion[]>("/api/practice/mastered"),
    /** 「掌握 ✓」= 服务端打上 mastered_at（软删除），不是真删 —— 真删会让「已掌握」永远是空的 */
    deleteWrongQuestion: (id: string) => request<null>(`/api/practice/wrong/${id}`, { method: "DELETE" }),
    explain: (text: string) =>
      request<ExplainResponse>("/api/explain", { method: "POST", body: JSON.stringify({ text }) }),
    termAsk: (body: TermAskRequest) =>
      request<TermAskResponse>("/api/explain/term/ask", { method: "POST", body: JSON.stringify(body) }),
    activateInvite: (code: string) =>
      request<InviteStatus>("/api/invite/activate", { method: "POST", body: JSON.stringify({ code }) }),
    inviteStatus: () => request<InviteStatus>("/api/invite/status"),
    requestEmailCode: (body: EmailCodeRequest) =>
      request<{ message: string }>("/api/auth/email/code", { method: "POST", body: JSON.stringify(body) }),
    verifyEmailCode: (body: EmailCodeVerify) =>
      request<AuthResponse>("/api/auth/email/verify", { method: "POST", body: JSON.stringify(body) }),
    me: () => request<AuthUser>("/api/auth/session"),
    logout: () => request<null>("/api/auth/logout", { method: "POST" }),
    getProfile: () => request<Profile>("/api/profile"),
    updateProfile: (body: ProfileUpdate) =>
      request<Profile>("/api/profile", { method: "POST", body: JSON.stringify(body) }),
    getSubscription: () => request<SubscriptionResponse>("/api/subscription"),
    updateSubscription: (body: Subscription) =>
      request<SubscriptionResponse>("/api/subscription", { method: "POST", body: JSON.stringify(body) }),
    /** 通知与提醒（画布 25 / 3:2062）。没设置过时服务端返回「全关」的默认值。 */
    getNotifications: () => request<NotificationSettings>("/api/notifications"),
    updateNotifications: (body: NotificationSettingsUpdate) =>
      request<NotificationSettings>("/api/notifications", { method: "POST", body: JSON.stringify(body) }),
    /** 导出账号数据（各表原样带出，前端只负责下载）。 */
    exportAccount: () => request<AccountExport>("/api/account/export"),
    /** 注销账号并删除数据 —— **不可逆**，必须原样传确认词「注销账号」。 */
    deleteAccount: (confirm: string) =>
      request<null>("/api/account", { method: "DELETE", body: JSON.stringify({ confirm }) }),
    getReviewState: () => request<ReviewStateResponse>("/api/review/state"),
    gradeReview: (body: ReviewGrade) =>
      request<ReviewGradeResponse>("/api/review/grade", { method: "POST", body: JSON.stringify(body) }),
  };
}

export type Api = ReturnType<typeof createApi>;

export const api: Api = createApi(API_BASE, getDeviceId);

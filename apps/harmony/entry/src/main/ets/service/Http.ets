import { http } from '@kit.NetworkKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongHttp';

/** 非 HTTP 状态类失败（网络层异常 / 响应体不是 JSON）的哨兵状态码。 */
export const STATUS_LOCAL_FAILURE: number = -1;

/** HTTP 层错误：携带状态码，便于上层区分「响应不是 JSON」「HTTP 状态码异常」「内容不存在(404)」。 */
export class HttpError extends Error {
  readonly status: number;
  /**
   * 非 200 时的原始响应体。AI 接口把业务原因放在响应体的 `code` 里
   * （INVITE_REQUIRED / QUOTA_EXHAUSTED / RATE_LIMITED …），只看状态码无法区分。
   */
  readonly body: string;

  constructor(status: number, message: string, body: string = '') {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/**
 * 极简 JSON 客户端。
 *
 * 设计取舍：
 * - 只做 GET + JSON 解析，不引入第三方网络库（原生端首版保持零依赖）。
 * - 每次请求显式 destroy，避免连接泄漏。
 * - 超时显式设置：移动网络下不能依赖默认值。
 * - **失败一律打 hilog**：首版没有日志，线上只看到笼统的「网络异常」，
 *   排查时无法区分「连不通」与「拿到的不是 JSON」，只能靠猜 —— 这是教训。
 */
export class HttpClient {
  static async getJson<T>(url: string): Promise<T> {
    return HttpClient.send<T>(http.RequestMethod.GET, url, HttpClient.jsonHeaders(), null);
  }

  /**
   * POST JSON。用于 AI 解析等需要提交正文的接口。
   * `headers` 由调用方给出——AI 接口要求 `X-Device-Id`，而内容接口不需要，
   * 不宜在通用层写死。
   */
  static async postJson<T>(url: string, body: string, headers: Record<string, string>): Promise<T> {
    return HttpClient.send<T>(http.RequestMethod.POST, url, headers, body);
  }

  private static async send<T>(
    method: http.RequestMethod,
    url: string,
    headers: Record<string, string>,
    body: string | null,
  ): Promise<T> {
    const requester: http.HttpRequest = http.createHttp();
    try {
      const options: http.HttpRequestOptions = {
        method: method,
        header: headers,
        connectTimeout: 10000,
        readTimeout: 15000,
        expectDataType: http.HttpDataType.STRING,
      };
      if (body !== null) {
        options.extraData = body;
      }
      const response: http.HttpResponse = await requester.request(url, options);
      const payload: string = typeof response.result === 'string'
        ? response.result
        : JSON.stringify(response.result);

      if (response.responseCode !== 200) {
        hilog.error(DOMAIN, TAG, '%{public}s %{public}s -> HTTP %{public}d | body=%{public}s',
          method, url, response.responseCode, HttpClient.head(payload));
        throw new HttpError(response.responseCode, `HTTP ${response.responseCode}`, payload);
      }

      const parsed: T | null = HttpClient.parse<T>(payload);
      if (parsed === null) {
        // 典型场景：/content/* 未部署时，Pages 会用站点首页/404 页兜底，返回 200 + text/html。
        hilog.error(DOMAIN, TAG, '%{public}s %{public}s -> HTTP 200 but NOT JSON | body=%{public}s',
          method, url, HttpClient.head(payload));
        throw new HttpError(STATUS_LOCAL_FAILURE,
          '响应不是 JSON：内容通道可能尚未部署（/content/* 会命中站点回退页）');
      }
      return parsed;
    } catch (err) {
      // ArkTS 要求对可能抛异常的调用显式处理（arkts-require-explicit-handling）。
      // 原样重抛，保持错误类型不被抹平：上层按 HttpError.status 分类。
      const cause: Error = err as Error;
      throw cause;
    } finally {
      requester.destroy();
    }
  }

  /** 只解析；失败返回 null（不抛），便于上层给出可执行提示。 */
  private static parse<T>(body: string): T | null {
    try {
      return JSON.parse(body) as T;
    } catch (err) {
      return null;
    }
  }

  /** 日志里只保留响应体开头，避免把整页 HTML 打进日志。 */
  private static head(body: string): string {
    const limit: number = 120;
    const flat: string = body.replace(/\s+/g, ' ').trim();
    return flat.length > limit ? flat.substring(0, limit) : flat;
  }

  private static jsonHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Accept': 'application/json' };
    return headers;
  }
}

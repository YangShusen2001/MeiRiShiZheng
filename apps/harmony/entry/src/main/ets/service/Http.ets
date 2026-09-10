import { http } from '@kit.NetworkKit';

/** HTTP 层错误：携带状态码，便于上层区分「内容未部署(404)」与「网络不可达」。 */
export class HttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * 极简 JSON 客户端。
 *
 * 设计取舍：
 * - 只做 GET + JSON 解析，不引入第三方网络库（原生端首版保持零依赖）。
 * - 每次请求显式 destroy，避免连接泄漏。
 * - 超时显式设置：移动网络下不能依赖默认值。
 */
export class HttpClient {
  static async getJson<T>(url: string): Promise<T> {
    const requester: http.HttpRequest = http.createHttp();
    try {
      const options: http.HttpRequestOptions = {
        method: http.RequestMethod.GET,
        header: HttpClient.jsonHeaders(),
        connectTimeout: 10000,
        readTimeout: 15000,
        expectDataType: http.HttpDataType.STRING,
      };
      const response: http.HttpResponse = await requester.request(url, options);
      const body: string = typeof response.result === 'string'
        ? response.result
        : JSON.stringify(response.result);
      if (response.responseCode !== 200) {
        throw new HttpError(response.responseCode, `HTTP ${response.responseCode}`);
      }
      return JSON.parse(body) as T;
    } finally {
      requester.destroy();
    }
  }

  private static jsonHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Accept': 'application/json' };
    return headers;
  }
}

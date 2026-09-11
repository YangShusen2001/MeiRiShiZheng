import { Endpoints } from '../config/Endpoints';
import { HttpClient, HttpError, STATUS_LOCAL_FAILURE } from './Http';
import { Net } from './Net';
import { Settings } from './Settings';

/**
 * 服务端错误码（见 `apps/api/src/routes/explain.ts`），必须与后端保持一致。
 * 导出给页面用于判断"能否重试"——页面不该自己写死字符串。
 */
export const CODE_INVITE_REQUIRED: string = 'INVITE_REQUIRED';
export const CODE_QUOTA_EXHAUSTED: string = 'QUOTA_EXHAUSTED';
export const CODE_RATE_LIMITED: string = 'RATE_LIMITED';
export const CODE_AI_UNAVAILABLE: string = 'AI_UNAVAILABLE';
export const CODE_AI_ERROR: string = 'AI_ERROR';
/** 本地原因码（非服务端返回）：网络层失败。 */
export const CODE_NETWORK: string = 'NETWORK';

const TEXT_LIMIT: number = 500;

/** 服务端统一响应包。 */
interface ExplainEnvelope {
  ok: boolean;
  data?: ExplainData;
}

interface ExplainData {
  explanation: string;
}

/** 错误响应包：真实结构是 `{ ok: false, error: { code, message } }` —— code 是**嵌套**的。
 *  （这条是实测出来的：`POST /api/explain` 返回
 *   `403 {"ok":false,"error":{"code":"INVITE_REQUIRED","message":"…"}}`。
 *   按平铺 `parsed.code` 取会永远拿不到，退化成"HTTP 403"，错误文案全失效。） */
interface ErrorEnvelope {
  error?: ErrorBody;
}

interface ErrorBody {
  code?: string;
  message?: string;
}

/** AI 调用结果。统一成"要么给解释、要么给一句可直接展示的话"，页面不必再判空。 */
export interface AiResult {
  ok: boolean;
  /** 成功为解释正文；失败为可直接展示给用户的说明。 */
  text: string;
  /** 失败原因码；成功为空串。用于区分"可重试"与"要去找管理员"。 */
  code: string;
}

/**
 * AI 能力客户端。
 *
 * ## 为什么必须走服务端
 * DeepSeek 密钥**只存在于 Worker 环境变量**（`DEEPSEEK_API_KEY`），客户端不持有、也不能持有。
 * 这条是硬约束：密钥一旦进包就等于公开。
 *
 * ## 服务端的门禁（决定了这里要做哪几种错误态）
 * - 匿名用户需**邀请码激活**且有额度，否则 403 `INVITE_REQUIRED` / `QUOTA_EXHAUSTED`；
 * - 每设备**每分钟 10 次**，超出 429 `RATE_LIMITED`；
 * - 服务端未配置密钥时 503 `AI_UNAVAILABLE`。
 * 四种原因的**处置动作完全不同**（找邀请码 / 等一会儿 / 找管理员 / 重试），
 * 所以这里不能笼统报"AI 失败"，必须逐个映射成可执行的话。
 */
export class Ai {
  /**
   * 该错误能否通过「激活邀请码」解决。
   * 邀请码缺失与额度用尽都可以靠换/填邀请码继续；限流、未配置密钥则不能——
   * 页面据此决定要不要把激活入口摆出来。
   */
  static needsInvite(code: string): boolean {
    return code === CODE_INVITE_REQUIRED || code === CODE_QUOTA_EXHAUSTED;
  }

  static async explain(text: string): Promise<AiResult> {
    const trimmed: string = text.trim();
    if (trimmed.length === 0) {
      return Ai.failure('', '这段内容为空，无法解析。');
    }
    if (trimmed.length > TEXT_LIMIT) {
      // 不静默截断——截断后的文本语义会变，AI 解释反而失真。
      return Ai.failure('', `这段内容有 ${trimmed.length} 字，超出 AI 解析上限（${TEXT_LIMIT} 字）。请换一段更短的文本。`);
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-Device-Id': Settings.deviceId(),
    };
    const body: string = JSON.stringify({ text: trimmed });

    try {
      const envelope: ExplainEnvelope = await HttpClient.postJson<ExplainEnvelope>(
        Endpoints.explainUrl(), body, headers);
      const data: ExplainData | undefined = envelope.data;
      const explanation: string = data === undefined ? '' : data.explanation.trim();
      if (explanation.length === 0) {
        return Ai.failure(CODE_AI_ERROR, 'AI 没有返回内容，请稍后重试。');
      }
      return { ok: true, code: '', text: explanation };
    } catch (err) {
      const cause: Error = err as Error;
      if (cause instanceof HttpError) {
        const code: string = Ai.codeOf(cause);
        return Ai.failure(code, Ai.messageFor(code, cause.status));
      }
      return Ai.failure(CODE_NETWORK, Net.isOnline()
        ? `请求失败：${cause.message}`
        : '当前无网络连接，请检查网络后重试。');
    }
  }

  private static failure(code: string, text: string): AiResult {
    return { ok: false, code: code, text: text };
  }

  /** 从响应体里取业务错误码；解析失败不抛，交给状态码兜底。 */
  private static codeOf(err: HttpError): string {
    if (err.body.length === 0) {
      return '';
    }
    try {
      const parsed: ErrorEnvelope = JSON.parse(err.body) as ErrorEnvelope;
      const body: ErrorBody | undefined = parsed.error;
      if (body === undefined) {
        return '';
      }
      const code: string | undefined = body.code;
      return code === undefined ? '' : code;
    } catch (parseErr) {
      return '';
    }
  }

  /** 错误码 → 可执行的人话。措辞要让用户知道下一步做什么。 */
  private static messageFor(code: string, status: number): string {
    if (code === CODE_INVITE_REQUIRED) {
      return 'AI 解析需要邀请码或登录（本版本还没有登录入口）。当前可先看文中已有的 AI 标注与释义。';
    }
    if (code === CODE_QUOTA_EXHAUSTED) {
      return '邀请码额度已用完，请联系管理员获取新邀请码。';
    }
    if (code === CODE_RATE_LIMITED) {
      return '请求过于频繁（每分钟最多 10 次），请稍等片刻再试。';
    }
    if (code === CODE_AI_UNAVAILABLE) {
      return '服务端还没有配置 AI 密钥，请联系管理员。';
    }
    if (code === CODE_AI_ERROR) {
      return 'AI 暂时不可用，请稍后重试。';
    }
    if (status === STATUS_LOCAL_FAILURE) {
      return '响应格式异常（不是 JSON），服务可能未正确部署。';
    }
    return `请求失败：HTTP ${status}`;
  }
}

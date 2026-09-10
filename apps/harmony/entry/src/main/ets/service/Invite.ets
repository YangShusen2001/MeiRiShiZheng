import { Endpoints } from '../config/Endpoints';
import { HttpClient, HttpError } from './Http';
import { Net } from './Net';
import { Settings } from './Settings';

/** 服务端错误码（见 `apps/api/src/routes/invite.ts`）。 */
const CODE_IDENTITY_REQUIRED: string = 'IDENTITY_REQUIRED';
const CODE_INVITE_NOT_FOUND: string = 'INVITE_NOT_FOUND';
const CODE_INVITE_EXHAUSTED: string = 'INVITE_EXHAUSTED';

/** 统一响应包。成功 `{ ok, data }`；失败 `{ ok:false, error:{ code, message } }`（实测确认）。 */
interface Envelope {
  ok: boolean;
  data?: InviteData;
  error?: ErrorBody;
}

interface InviteData {
  active: boolean;
  remaining: number;
  code: string;
}

interface ErrorBody {
  code?: string;
  message?: string;
}

/** 激活结果。`ok` 为真时 `remaining` 有效。 */
export interface InviteResult {
  ok: boolean;
  /** 可直接展示的一句话。 */
  text: string;
  remaining: number;
}

/**
 * 邀请码激活。
 *
 * ## 为什么 App 内要做这个
 * 服务端对匿名用户是「先激活邀请码、再按额度消耗」的模型。
 * 如果端上不提供激活入口，AI 功能对未登录用户就永远停在
 * `INVITE_REQUIRED` —— 功能等于不存在。补这个入口，AI 才真正可用。
 *
 * ## 身份
 * 用持久化的 `X-Device-Id` 作为 owner（与 AI 接口同一身份），
 * 所以激活一次之后，同设备后续调用就能直接用。
 */
export class Invite {
  static async activate(code: string): Promise<InviteResult> {
    const trimmed: string = code.trim();
    if (trimmed.length === 0) {
      return { ok: false, text: '请输入邀请码。', remaining: 0 };
    }
    if (trimmed.length > 64) {
      return { ok: false, text: '邀请码格式不对（最长 64 位）。', remaining: 0 };
    }
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-Device-Id': Settings.deviceId(),
    };
    try {
      const envelope: Envelope = await HttpClient.postJson<Envelope>(
        Endpoints.inviteActivateUrl(), JSON.stringify({ code: trimmed }), headers);
      const data: InviteData | undefined = envelope.data;
      if (data === undefined) {
        return { ok: false, text: '激活失败：服务未返回数据。', remaining: 0 };
      }
      return { ok: true, text: `激活成功，AI 解析剩余 ${data.remaining} 次。`, remaining: data.remaining };
    } catch (err) {
      const cause: Error = err as Error;
      if (cause instanceof HttpError) {
        const code: string = Invite.codeOf(cause);
        return { ok: false, text: Invite.messageFor(code, cause.status), remaining: 0 };
      }
      return {
        ok: false,
        remaining: 0,
        text: Net.isOnline() ? `请求失败：${cause.message}` : '当前无网络连接，请检查网络后重试。',
      };
    }
  }

  private static codeOf(err: HttpError): string {
    if (err.body.length === 0) {
      return '';
    }
    try {
      const parsed: Envelope = JSON.parse(err.body) as Envelope;
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

  private static messageFor(code: string, status: number): string {
    if (code === CODE_INVITE_NOT_FOUND) {
      return '邀请码不存在，请核对后重试。';
    }
    if (code === CODE_INVITE_EXHAUSTED) {
      return '这个邀请码的额度已用完，请换一个或联系管理员。';
    }
    if (code === CODE_IDENTITY_REQUIRED) {
      return '缺少设备标识，激活失败。请重启应用后重试。';
    }
    return `激活失败：HTTP ${status}`;
  }
}

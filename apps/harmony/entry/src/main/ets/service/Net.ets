import { connection } from '@kit.NetworkKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongNet';

/**
 * 网络可达性。
 *
 * 两种用法缺一不可：
 * - `probe()` —— 请求失败时**探测一次**，把「设备没联网」与「服务返回异常」分开，
 *   否则用户不知道该去修什么（关 WiFi？还是稍后重试？）；
 * - `watch()` —— **持续监听**，断网时主动挂提示条，而不是等用户点了才报错。
 *
 * 探测失败时**不武断判离线**，交给真正的请求去失败并给出准确原因。
 */
export class Net {
  private static watcher: connection.NetConnection | null = null;
  /** 最近一次已知在线状态；未知时按在线处理（不误报）。 */
  private static online: boolean = true;

  /** 同步读取最近已知状态（不发起探测）。 */
  static isOnline(): boolean {
    return Net.online;
  }

  static async probe(): Promise<boolean> {
    try {
      const handle: connection.NetHandle = await connection.getDefaultNet();
      Net.online = handle.netId !== 0;
    } catch (err) {
      Net.online = true;
    }
    return Net.online;
  }

  /**
   * 开始监听网络变化。幂等：重复调用不会注册多份。
   * `onChange` 只在状态**翻转时**回调，避免同一状态重复刷新 UI。
   */
  static watch(onChange: (online: boolean) => void): void {
    if (Net.watcher !== null) {
      return;
    }
    try {
      const watcher: connection.NetConnection = connection.createNetConnection();
      watcher.register((error) => {
        if (error) {
          hilog.warn(DOMAIN, TAG, '网络监听注册失败：%{public}s', JSON.stringify(error));
        }
      });
      watcher.on('netAvailable', () => {
        if (!Net.online) {
          Net.online = true;
          onChange(true);
        }
      });
      watcher.on('netLost', () => {
        if (Net.online) {
          Net.online = false;
          onChange(false);
        }
      });
      Net.watcher = watcher;
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '网络监听不可用（退化为失败时探测）：%{public}s', cause.message);
      Net.watcher = null;
    }
  }

  /** 停止监听。页面销毁时必须调用，否则监听器随页面泄漏。 */
  static unwatch(): void {
    const watcher: connection.NetConnection | null = Net.watcher;
    if (watcher === null) {
      return;
    }
    try {
      watcher.unregister((error) => {
        if (error) {
          hilog.warn(DOMAIN, TAG, '网络监听注销失败：%{public}s', JSON.stringify(error));
        }
      });
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '注销网络监听异常：%{public}s', cause.message);
    }
    Net.watcher = null;
  }
}

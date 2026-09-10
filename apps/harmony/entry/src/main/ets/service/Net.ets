import { connection } from '@kit.NetworkKit';

/**
 * 网络可达性探测。
 *
 * 用途：把「设备根本没联网」与「服务返回异常」在提示上分开——
 * 首版无论哪种情况都只说「网络异常」，用户不知道该去修什么（关 WiFi？还是稍后重试？）。
 *
 * 探测失败时**不武断判离线**（返回 true），交给真正的请求去失败并给出准确原因。
 */
export class Net {
  static async isOnline(): Promise<boolean> {
    try {
      const handle: connection.NetHandle = await connection.getDefaultNet();
      return handle.netId !== 0;
    } catch (err) {
      return true;
    }
  }
}

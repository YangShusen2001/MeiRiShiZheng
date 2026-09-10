import { pasteboard } from '@kit.BasicServicesKit';

/**
 * 系统剪贴板。
 *
 * 用途：阅读页「复制原文链接」。选择复制而非拉起系统分享面板——
 * 不引入 ShareExtension，零权限、零配置，且对「把链接发给自己/群里」这个真实场景足够。
 * 返回布尔值：失败必须让调用方知道，否则按钮点了没反应会被当成卡死。
 */
export class Clipboard {
  static async copyText(text: string): Promise<boolean> {
    try {
      const data: pasteboard.PasteData = pasteboard.createData(pasteboard.MIMETYPE_TEXT_PLAIN, text);
      const board: pasteboard.SystemPasteboard = pasteboard.getSystemPasteboard();
      await board.setData(data);
      return true;
    } catch (err) {
      return false;
    }
  }
}

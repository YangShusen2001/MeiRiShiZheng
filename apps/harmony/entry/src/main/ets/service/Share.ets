import { systemShare } from '@kit.ShareKit';
import { uniformTypeDescriptor as utd } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Settings } from './Settings';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongShare';

/**
 * 拉起系统分享面板。
 *
 * 为什么独立成一个小文件：`@kit.ShareKit` 的 `SharedData` / `ShareController` 构造参数
 * 在不同 SDK 版本上有差异（尤其 `utd` 字段）。**若编译不过，删掉本文件与阅读页里
 * 那一处调用即可**——「复制原文链接」是独立的备用路径，不受影响。
 *
 * context 取自 `Settings`（EntryAbility 初始化时已持有），避免在组件内使用
 * 获取 hostContext 的那套 API（跨版本行为不一致）。
 */
export class Share {
  static async shareText(title: string, content: string): Promise<boolean> {
    const context: common.UIAbilityContext | null = Settings.context();
    if (context === null) {
      return false;
    }
    try {
      const data: systemShare.SharedData = new systemShare.SharedData({
        utd: utd.UniformDataType.PLAIN_TEXT,
        content: content,
        title: title,
      });
      const controller: systemShare.ShareController = new systemShare.ShareController(data);
      await controller.show(context, {
        selectionMode: systemShare.SelectionMode.SINGLE,
        previewMode: systemShare.SharePreviewMode.DETAIL,
      });
      return true;
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '拉起系统分享失败：%{public}s', cause.message);
      return false;
    }
  }
}

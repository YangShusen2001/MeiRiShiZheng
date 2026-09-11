import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { WindowManager } from '@kit.SpeechKit';
import { Settings } from '../service/Settings';
import { Speech } from '../service/Speech';

const DOMAIN: number = 0x0000;
const TAG: string = 'Kaogong';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // 读取用户偏好（深浅色 / 阅读档位）并写入 AppStorage，供令牌层与页面订阅。
    // 必须在此处初始化：只有 Ability 拿得到 context，Preferences 需要它。
    // 首版曾在此处强制固定浅色——那会导致系统深色永远失效，已移除。
    Settings.init(this.context);
    // 朗读控件提前初始化：首次点「听」时不用等初始化，避免开头被吞掉
    Speech.init(this.context).then((ok: boolean) => {
      hilog.info(DOMAIN, TAG, '朗读控件初始化：%{public}s', ok ? 'ok' : 'failed');
    });
    hilog.info(DOMAIN, TAG, 'onCreate');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    // 朗读控件要求传入 WindowStage（播放面板 / 悬浮窗依赖它）
    WindowManager.setWindowStage(windowStage);
    windowStage.loadContent('pages/Index', (err: BusinessError) => {
      if (err.code) {
        hilog.error(DOMAIN, TAG, 'loadContent failed: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(DOMAIN, TAG, 'loadContent succeeded');
    });
  }

  /** 退出时释放朗读控件（否则可能残留播放）。 */
  onDestroy(): void {
    Speech.stop();
    hilog.info(DOMAIN, TAG, 'onDestroy');
  }
}

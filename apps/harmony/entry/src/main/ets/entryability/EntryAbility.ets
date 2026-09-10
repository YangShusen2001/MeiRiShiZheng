import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { Settings } from '../service/Settings';

const DOMAIN: number = 0x0000;
const TAG: string = 'Kaogong';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // 读取用户偏好（深浅色 / 阅读档位）并写入 AppStorage，供令牌层与页面订阅。
    // 必须在此处初始化：只有 Ability 拿得到 context，Preferences 需要它。
    // 首版曾在此处强制固定浅色——那会导致系统深色永远失效，已移除。
    Settings.init(this.context);
    hilog.info(DOMAIN, TAG, 'onCreate');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err: BusinessError) => {
      if (err.code) {
        hilog.error(DOMAIN, TAG, 'loadContent failed: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(DOMAIN, TAG, 'loadContent succeeded');
    });
  }

  onDestroy(): void {
    hilog.info(DOMAIN, TAG, 'onDestroy');
  }
}

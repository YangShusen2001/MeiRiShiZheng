import { Settings } from '../service/Settings';
import { KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';

/**
 * 阅读设置面板：字号档位 + 深色模式。
 *
 * 设计取舍：
 * - **带实时预览**——调字号却看不到效果，等于盲调；预览行用当前档位渲染一句真实场景的文本，
 *   用户在面板里就能判断合不合适，不用退出去看正文。
 * - **档位用离散值而非滑杆**——阅读档位需要可预期的排版结果（行高联动），
 *   滑杆会产生无数个中间态，反而难以收敛到合适的阅读密度。
 * - 面板本身只负责"设置内容"，浮层容器（遮罩 + 圆角）由调用方提供，
 *   这样首页与阅读页可以各自决定浮层形态。
 *
 * 无障碍：所有可点元素高度 ≥44vp；选中态除颜色外**另有文字加粗**，
 * 不依赖颜色单独传达状态。
 */
@Component
export struct SettingsSheet {
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;
  /** 关闭回调由父组件注入。 */
  onClose: () => void = () => {
  };

  @Builder
  stepChip(label: string, index: number) {
    Text(label)
      .fontSize(KFont.meta())
      .fontWeight(Settings.fontStepIndex() === index ? FontWeight.Bold : FontWeight.Normal)
      .fontColor(Settings.fontStepIndex() === index ? KColor.surface() : KColor.sub())
      .backgroundColor(Settings.fontStepIndex() === index ? KColor.primary() : KColor.surface())
      .borderRadius(KRadius.S)
      .borderWidth(1)
      .borderColor(Settings.fontStepIndex() === index ? KColor.primary() : KColor.line())
      .height(KSize.TOUCH_MIN)
      .layoutWeight(1)
      .textAlign(TextAlign.Center)
      .onClick(() => {
        Settings.setFontStep(index);
      })
  }

  /** 朗读速度档位；选中态除配色外**另有加粗**，不靠颜色单独表意。 */
  @Builder
  speedChip(label: string, index: number) {
    Text(label)
      .fontSize(KFont.meta())
      .fontWeight(Settings.speedStepIndex() === index ? FontWeight.Bold : FontWeight.Normal)
      .fontColor(Settings.speedStepIndex() === index ? KColor.surface() : KColor.sub())
      .backgroundColor(Settings.speedStepIndex() === index ? KColor.primary() : KColor.surface())
      .borderRadius(KRadius.S)
      .borderWidth(1)
      .borderColor(Settings.speedStepIndex() === index ? KColor.primary() : KColor.line())
      .height(KSize.TOUCH_MIN)
      .layoutWeight(1)
      .textAlign(TextAlign.Center)
      .onClick(() => {
        Settings.setSpeedStep(index);
      })
  }

  build() {
    Column() {
      Row() {
        Text('阅读设置')
          .fontSize(KFont.titleS())
          .fontWeight(FontWeight.Bold)
          .fontColor(KColor.ink())
        Blank()
        Text('关闭')
          .fontSize(KFont.meta())
          .fontColor(KColor.sub())
          .height(KSize.TOUCH_MIN)
          .padding({ left: KSpace.M, right: KSpace.M })
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.onClose();
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text('字号')
        .fontSize(KFont.caption())
        .fontColor(KColor.sub())
        .margin({ top: KSpace.M })

      Row() {
        ForEach(Settings.FONT_LABELS, (label: string, index: number) => {
          this.stepChip(label, index)
        }, (label: string) => label)
      }
      .width('100%')
      .margin({ top: KSpace.S })

      // 实时预览：用当前档位渲染，避免盲调
      Text('预览：基层治理的关键在于把矛盾化解在基层。')
        .fontSize(KFont.body())
        .lineHeight(KLine.relaxed())
        .fontColor(KColor.ink())
        .width('100%')
        .padding(KSpace.M)
        .margin({ top: KSpace.M })
        .backgroundColor(KColor.surface())
        .borderRadius(KRadius.S)

      Row() {
        Text('深色模式')
          .fontSize(KFont.meta())
          .fontColor(KColor.ink())
        Blank()
        Toggle({ type: ToggleType.Switch, isOn: this.darkMode })
          .onChange((isOn: boolean) => {
            Settings.setDark(isOn);
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .constraintSize({ minHeight: KSize.TOUCH_MIN })
      .margin({ top: KSpace.M })

      Text('朗读速度')
        .fontSize(KFont.caption())
        .fontColor(KColor.sub())
        .margin({ top: KSpace.M })

      Row() {
        ForEach(Settings.SPEED_LABELS, (label: string, index: number) => {
          this.speedChip(label, index)
        }, (label: string) => label)
      }
      .width('100%')
      .margin({ top: KSpace.S })

      Row() {
        Column() {
          Text('在线音质')
            .fontSize(KFont.meta())
            .fontColor(KColor.ink())
          Text('用云端发音人，音色更自然；但朗读时需要联网')
            .fontSize(KFont.caption())
            .lineHeight(KLine.tight())
            .fontColor(KColor.mut())
            .margin({ top: KSpace.HAIR })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Toggle({ type: ToggleType.Switch, isOn: Settings.speakOnline() })
          .onChange((isOn: boolean) => {
            Settings.setSpeakOnline(isOn);
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .constraintSize({ minHeight: KSize.TOUCH_MIN })
      .margin({ top: KSpace.M })

      Text('字号影响全部正文与标签（系统绘制的导航栏除外）。深色模式用深暖灰而非纯黑，避免夜间反光。朗读默认走离线引擎——通勤没网也能听；追求音色可打开在线音质。')
        .fontSize(KFont.caption())
        .lineHeight(KLine.tight())
        .fontColor(KColor.mut())
        .width('100%')
        .margin({ top: KSpace.M })
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: KSpace.L, right: KSpace.L, top: KSpace.M, bottom: KSpace.XXL })
    .backgroundColor(KColor.surfaceAlt())
    .borderRadius({ topLeft: KRadius.XL, topRight: KRadius.XL })
    // 入场动效加在根节点上——@Builder 调用返回 void，调用方无法链式加属性
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 60 })))
  }
}

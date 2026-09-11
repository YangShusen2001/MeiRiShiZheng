import { ContentService } from '../service/ContentService';
import { CardState, DueCard, GRADE_EASY, GRADE_FORGOT, GRADE_RECALLED, Review, ReviewCard } from '../service/Review';
import { KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';

/**
 * 考点复习页（间隔重复）。
 *
 * ## 交互设计取舍
 * - **一屏一张卡**：复习时干扰越少越好，不放列表、不放侧栏。
 * - **评分按钮直接显示"下次间隔"**（1 天后 / 6 天后 / …）：
 *   让用户理解自己这次选择的后果，而不是盲点"记得/不记得"。
 * - **忘了 → 10 分钟后再出现**（同一会话内补一次），不排到明天。
 * - **完成态给反馈**：今日复习 N 张 + 下次到期时间，
 *   让"我进步了"这件事可见——这是留存的关键。
 *
 * ## 空态（三种，都要给可执行方向）
 * 1. 没有卡片：说明题库来源，指向阅读页
 * 2. 有卡片但今天没有到期的：告诉用户下次到期时间
 * 3. 加载失败：区分没联网/服务异常，给重试
 */
@Component
export struct ReviewPage {
  @Consume('navStack') navStack: NavPathStack;
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;
  @State loading: boolean = true;
  @State errorText: string = '';
  @State cached: boolean = false;
  @State queue: DueCard[] = [];
  @State index: number = 0;
  @State revealed: boolean = false;
  @State doneCount: number = 0;
  /** 全部卡片（用于统计"下次到期"）。非状态：只在加载时赋值。 */
  private allCards: ReviewCard[] = [];

  aboutToAppear(): void {
    this.load();
  }

  private load(): void {
    this.loading = true;
    this.errorText = '';
    Review.loadCards()
      .then((loaded) => {
        this.allCards = loaded.data;
        this.cached = loaded.cached;
        const states = Review.readState();
        this.queue = Review.dueCards(this.allCards, states);
        this.index = 0;
        this.revealed = false;
        this.doneCount = 0;
        this.loading = false;
      })
      .catch((err: Error) => {
        this.errorText = `无法加载题库：${err.message}`;
        this.loading = false;
      });
  }

  private current(): DueCard | null {
    if (this.index < 0 || this.index >= this.queue.length) {
      return null;
    }
    return this.queue[this.index];
  }

  private grade(value: number): void {
    const item: DueCard | null = this.current();
    if (item === null) {
      return;
    }
    Review.record(item.card.id, value);
    this.doneCount = this.doneCount + 1;
    this.index = this.index + 1;
    this.revealed = false;
  }

  /** 评分按钮上的"下次间隔"预览——把选择的后果直接摆出来。 */
  private nextGapText(value: number): string {
    const item: DueCard | null = this.current();
    if (item === null) {
      return '';
    }
    const next = Review.schedule(item.state, value);
    if (next.intervalDays <= 0) {
      return '10 分钟后';
    }
    return `${next.intervalDays} 天后`;
  }

  private switchTagText(): string {
    const item: DueCard | null = this.current();
    if (item === null || item.card.tags.length === 0) {
      return '';
    }
    return item.card.tags.join(' · ');
  }

  /** 最近的下次到期（用于完成态/无到期态）。 */
  private nextDueText(): string {
    const map: Map<string, CardState> = Review.stateMap(Review.readState());
    let earliest: number = 0;
    for (const card of this.allCards) {
      const state: CardState | undefined = map.get(card.id);
      if (state === undefined) {
        continue;
      }
      if (earliest === 0 || state.due < earliest) {
        earliest = state.due;
      }
    }
    if (earliest === 0) {
      return '';
    }
    const days: number = Math.max(1, Math.round((earliest - Date.now()) / 86400000));
    return `${days} 天后`;
  }

  @Builder
  gradeButton(label: string, hint: string, value: number, primary: boolean) {
    Column() {
      Text(label)
        .fontSize(KFont.body())
        .fontWeight(FontWeight.Medium)
        .fontColor(primary ? KColor.surface() : KColor.primaryText())
      Text(hint)
        .fontSize(KFont.caption())
        .fontColor(primary ? KColor.surface() : KColor.mut())
        .margin({ top: KSpace.HAIR })
    }
    .alignItems(HorizontalAlign.Center)
    .justifyContent(FlexAlign.Center)
    .layoutWeight(1)
    .constraintSize({ minHeight: KSize.TOUCH_MIN + 12 })
    .backgroundColor(primary ? KColor.primary() : KColor.surface())
    .borderRadius(KRadius.S)
    .borderWidth(primary ? 0 : 1)
    .borderColor(KColor.line())
    .margin({ left: KSpace.S })
    .onClick(() => {
      this.grade(value);
    })
  }

  @Builder
  emptyState(title: string, desc: string) {
    Column() {
      Text(title)
        .fontSize(KFont.titleS())
        .fontWeight(FontWeight.Bold)
        .fontColor(KColor.ink())
      Text(desc)
        .fontSize(KFont.meta())
        .lineHeight(KLine.tight())
        .fontColor(KColor.sub())
        .margin({ top: KSpace.S })
        .textAlign(TextAlign.Center)
      Text('去读今日文章')
        .fontSize(KFont.meta())
        .fontColor(KColor.primaryText())
        .backgroundColor(KColor.primarySoft())
        .borderRadius(KRadius.S)
        .height(KSize.TOUCH_MIN)
        .padding({ left: KSpace.L, right: KSpace.L })
        .margin({ top: KSpace.XL })
        .textAlign(TextAlign.Center)
        .onClick(() => {
          this.navStack.pop();
        })
    }
    .width('100%')
    .padding(KSpace.XXL)
    .margin({ top: KSpace.XXXL })
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
  }

  @Builder
  body() {
    Column() {
      if (this.loading) {
        Row() {
          LoadingProgress().width(28).height(28)
          Text('正在准备复习卡片…')
            .fontSize(KFont.meta())
            .fontColor(KColor.sub())
            .margin({ left: KSpace.M })
        }
        .margin({ top: KSpace.XXXL })
      } else if (this.errorText.length > 0) {
        Column() {
          Text('无法加载题库')
            .fontSize(KFont.titleS())
            .fontWeight(FontWeight.Bold)
            .fontColor(KColor.danger())
          Text(this.errorText)
            .fontSize(KFont.meta())
            .lineHeight(KLine.tight())
            .fontColor(KColor.sub())
            .margin({ top: KSpace.S })
            .textAlign(TextAlign.Center)
          Button('重试')
            .height(KSize.TOUCH_MIN)
            .margin({ top: KSpace.XL })
            .onClick(() => {
              this.load();
            })
        }
        .width('100%')
        .padding(KSpace.XXL)
        .margin({ top: KSpace.XXXL })
        .backgroundColor(KColor.surface())
        .borderRadius(KRadius.L)
      } else if (this.allCards.length === 0) {
        this.emptyState('题库还是空的', '卡片由内容管道从每日选中的文章里提炼。先在首页读几篇，题库会逐步积累。')
      } else if (this.current() === null) {
        this.emptyState(
          '今日复习完成',
          `本次复习了 ${this.doneCount} 张卡片。${this.nextDueText().length > 0 ? `下一批将在 ${this.nextDueText()}到期。` : '继续积累卡片即可持续复习。'}`,
        )
      } else {
        // 进度
        Text(`第 ${this.index + 1} / ${this.queue.length} 张` + (this.cached ? ' · 离线题库' : ''))
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .width('100%')

        // 问题
        Column() {
          if (this.switchTagText().length > 0) {
            Text(this.switchTagText())
              .fontSize(KFont.caption())
              .fontColor(KColor.primaryText())
              .backgroundColor(KColor.primarySoft())
              .borderRadius(KRadius.XS)
              .padding({ left: KSpace.S, right: KSpace.S, top: KSpace.HAIR, bottom: KSpace.HAIR })
          }
          Text(this.current()?.card.question ?? '')
            .fontSize(KFont.titleS())
            .lineHeight(KLine.normal())
            .fontColor(KColor.ink())
            .margin({ top: KSpace.S })
            .width('100%')
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding(KSpace.L)
        .margin({ top: KSpace.M })
        .backgroundColor(KColor.surface())
        .borderRadius(KRadius.L)

        if (!this.revealed) {
          Text('显示答案')
            .fontSize(KFont.body())
            .fontWeight(FontWeight.Medium)
            .fontColor(KColor.surface())
            .backgroundColor(KColor.primary())
            .borderRadius(KRadius.S)
            .height(KSize.TOUCH_MIN + 8)
            .width('100%')
            .textAlign(TextAlign.Center)
            .margin({ top: KSpace.XL })
            .onClick(() => {
              this.revealed = true;
            })
        } else {
          Text(this.current()?.card.answer ?? '')
            .fontSize(KFont.body())
            .lineHeight(KLine.relaxed())
            .fontColor(KColor.ink())
            .width('100%')
            .padding(KSpace.L)
            .margin({ top: KSpace.M })
            .backgroundColor(KColor.surfaceAlt())
            .borderRadius(KRadius.L)

          Row() {
            this.gradeButton('忘了', this.nextGapText(GRADE_FORGOT), GRADE_FORGOT, false)
            this.gradeButton('想起', this.nextGapText(GRADE_RECALLED), GRADE_RECALLED, true)
            this.gradeButton('太简单', this.nextGapText(GRADE_EASY), GRADE_EASY, false)
          }
          .width('100%')
          .margin({ top: KSpace.XL })
        }
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ left: KSpace.PAGE, right: KSpace.PAGE, top: KSpace.M, bottom: KSpace.XXL })
  }

  build() {
    NavDestination() {
      Scroll() {
        this.body()
      }
      .width('100%')
      .height('100%')
      .align(Alignment.Top)
      .scrollBar(BarState.Off)
      .backgroundColor(KColor.bg())
    }
    .title('考点复习')
    .backgroundColor(KColor.bg())
  }
}

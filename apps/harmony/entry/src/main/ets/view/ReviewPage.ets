import { CardState, Choice, GRADE_EASY, GRADE_FORGOT, GRADE_RECALLED, OPTION_LETTERS, QuizCard, Review, ReviewCard } from '../service/Review';
import { KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';

/**
 * 考点复习页（间隔重复 · ABCD 单选）。
 *
 * ## 为什么是选择题
 * 考公笔试（行测常识 / 公基）本就是选择题形态，用户在这种形态下更容易进入状态；
 * 更重要的是**判定客观**——自评"记得 / 不记得"会自我欺骗，选错就是选错。
 *
 * ## 评分与调度
 * 判定结果自动映射到 SM-2：答错 → 忘了（10 分钟后重现）；答对 → 想起。
 * 答对后额外给一个「太简单」把间隔拉长——这是唯一的自评入口，
 * 且只在"已证明答对"之后才可用。
 *
 * **一次复习只记一次分**：选中选项时**不记分**，点「下一题」/「太简单」时才记。
 * 否则同一张卡会被记两次，间隔被重复放大。
 *
 * ## 降级
 * 造不出 3 个合格干扰项的卡（见 `Review.buildQuiz` 的三重过滤）走**自评模式**：
 * 显示答案 → 三档评分。宁可降级，也不能出一道有两个正确选项的题。
 */
@Component
export struct ReviewPage {
  @Consume('navStack') navStack: NavPathStack;
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;
  @State loading: boolean = true;
  @State errorText: string = '';
  @State cached: boolean = false;
  @State quiz: QuizCard[] = [];
  @State index: number = 0;
  /** 已选中的选项下标；-1 表示尚未作答。 */
  @State answered: number = -1;
  /** 自评模式的答案是否已展开。 */
  @State revealed: boolean = false;
  @State doneCount: number = 0;
  /** 上一题是否答对（决定「下一题」按哪档记分）。 */
  @State lastCorrect: boolean = false;
  /** 全部卡片（用于统计"下次到期"）。非状态：只在加载时赋值。 */
  private allCards: ReviewCard[] = [];
  /** 缓存的题目引用：避免 @Builder 里反复调 current() 触发重复计算。 */
  @State fallbackMode: boolean = false;

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
        const due = Review.dueCards(this.allCards, Review.readState());
        this.quiz = Review.buildQuiz(due, this.allCards);
        this.index = 0;
        this.answered = -1;
        this.revealed = false;
        this.doneCount = 0;
        this.syncFallbackMode();
        this.loading = false;
      })
      .catch((err: Error) => {
        this.errorText = `无法加载题库：${err.message}`;
        this.loading = false;
      });
  }

  private current(): QuizCard | null {
    if (this.index < 0 || this.index >= this.quiz.length) {
      return null;
    }
    return this.quiz[this.index];
  }

  private syncFallbackMode(): void {
    const question: QuizCard | null = this.current();
    this.fallbackMode = question === null ? false : question.fallback;
  }

  /** 选中某个选项：只改状态，不记分（记分在「下一题」/「太简单」时做）。 */
  private pick(optionIndex: number): void {
    if (this.answered >= 0) {
      return;
    }
    const question: QuizCard | null = this.current();
    if (question === null || optionIndex < 0 || optionIndex >= question.options.length) {
      return;
    }
    this.answered = optionIndex;
    this.lastCorrect = question.options[optionIndex].correct;
  }

  private advance(grade: number): void {
    const question: QuizCard | null = this.current();
    if (question === null) {
      return;
    }
    Review.record(question.id, grade);
    this.doneCount = this.doneCount + 1;
    this.index = this.index + 1;
    this.answered = -1;
    this.revealed = false;
    this.syncFallbackMode();
  }

  /** 选择题提交：答对按"想起"，答错按"忘了"。 */
  private submitChoice(): void {
    this.advance(this.lastCorrect ? GRADE_RECALLED : GRADE_FORGOT);
  }

  // —— 选项配色与标记：对错**同时用颜色和符号**表达，不靠颜色单独表意 ——

  private optionBg(choice: Choice, optionIndex: number): string {
    if (this.answered < 0) {
      return KColor.surface();
    }
    if (choice.correct) {
      return KColor.primarySoft();
    }
    if (optionIndex === this.answered) {
      return KColor.dangerSoft();
    }
    return KColor.surface();
  }

  private optionBorder(choice: Choice, optionIndex: number): string {
    if (this.answered < 0) {
      return KColor.line();
    }
    if (choice.correct) {
      return KColor.primary();
    }
    if (optionIndex === this.answered) {
      return KColor.danger();
    }
    return KColor.lineSoft();
  }

  private optionInk(choice: Choice, optionIndex: number): string {
    if (this.answered < 0) {
      return KColor.ink();
    }
    if (choice.correct) {
      return KColor.primaryText();
    }
    if (optionIndex === this.answered) {
      return KColor.danger();
    }
    return KColor.mut();
  }

  /** 未作答显示字母；作答后正确项显 ✓、误选项显 ✗。 */
  private optionMark(choice: Choice, optionIndex: number): string {
    if (this.answered < 0) {
      return OPTION_LETTERS[optionIndex];
    }
    if (choice.correct) {
      return '✓';
    }
    if (optionIndex === this.answered) {
      return '✗';
    }
    return OPTION_LETTERS[optionIndex];
  }

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
  optionRow(choice: Choice, optionIndex: number) {
    Row() {
      Text(this.optionMark(choice, optionIndex))
        .fontSize(KFont.meta())
        .fontWeight(FontWeight.Bold)
        .fontColor(this.optionInk(choice, optionIndex))
        .width(KSpace.XXL)
        .textAlign(TextAlign.Center)
      Text(choice.text)
        .fontSize(KFont.meta())
        .lineHeight(KLine.normal())
        .fontColor(this.optionInk(choice, optionIndex))
        .layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .constraintSize({ minHeight: KSize.TOUCH_MIN })
    .padding(KSpace.M)
    .margin({ top: KSpace.S })
    .backgroundColor(this.optionBg(choice, optionIndex))
    .borderRadius(KRadius.S)
    .borderWidth(1)
    .borderColor(this.optionBorder(choice, optionIndex))
    .onClick(() => {
      this.pick(optionIndex);
    })
  }

  @Builder
  gradeButton(label: string, hint: string, grade: number, primary: boolean) {
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
      this.advance(grade);
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
  questionBlock(question: QuizCard) {
    Column() {
      if (question.tags.length > 0) {
        Text(question.tags.join(' · '))
          .fontSize(KFont.caption())
          .fontColor(KColor.primaryText())
          .backgroundColor(KColor.primarySoft())
          .borderRadius(KRadius.XS)
          .padding({ left: KSpace.S, right: KSpace.S, top: KSpace.HAIR, bottom: KSpace.HAIR })
      }
      Text(question.question)
        .fontSize(KFont.titleS())
        .lineHeight(KLine.normal())
        .fontColor(KColor.ink())
        .margin({ top: KSpace.S })
        .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(KSpace.L)
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
  }

  /** 判定后的操作条：答对给「太简单」，答错只给「下一题」。 */
  @Builder
  actionBar() {
    Row() {
      Text(this.lastCorrect ? '✓ 答对了' : '✗ 答错了')
        .fontSize(KFont.meta())
        .fontWeight(FontWeight.Medium)
        .fontColor(this.lastCorrect ? KColor.primaryText() : KColor.danger())
        .layoutWeight(1)

      if (this.lastCorrect) {
        Text('太简单')
          .fontSize(KFont.meta())
          .fontColor(KColor.sub())
          .borderWidth(1)
          .borderColor(KColor.line())
          .borderRadius(KRadius.S)
          .height(KSize.TOUCH_MIN)
          .padding({ left: KSpace.L, right: KSpace.L })
          .textAlign(TextAlign.Center)
          .margin({ right: KSpace.S })
          .onClick(() => {
            this.advance(GRADE_EASY);
          })
      }

      Text('下一题')
        .fontSize(KFont.meta())
        .fontWeight(FontWeight.Medium)
        .fontColor(KColor.surface())
        .backgroundColor(KColor.primary())
        .borderRadius(KRadius.S)
        .height(KSize.TOUCH_MIN)
        .padding({ left: KSpace.XL, right: KSpace.XL })
        .textAlign(TextAlign.Center)
        .onClick(() => {
          this.submitChoice();
        })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .margin({ top: KSpace.XL })
  }

  /**
   * 判定后的解析。
   *
   * ## 为什么必须有
   * 只给 ✓/✗ 与正确答案，用户**错了也不知道为什么错**——刷题等于白刷。
   *
   * ## 为什么这里没有逐项详解（如实说明）
   * 卡片数据里没有 `explain` 字段，端上也不该自己编解析。
   * 但**干扰项的构造方式本身就是有效信息**：四个选项都是同一批官方表述，
   * 区分点在于「各自回答的是哪个问题」——把这一点说清楚，
   * 用户下次看到同类表述就知道该怎么分辨。这是不留 AI 也能给出的真解析。
   *
   * 逐项详解需要管道为每张卡生成 `explain`（属后续接入 AI 的一步），
   * 所以这里明确标注"归属与出处"，而不是假装有详解。
   */
  @Builder
  explainBlock(question: QuizCard) {
    Column() {
      Text('解析')
        .fontSize(KFont.caption())
        .fontColor(KColor.sub())

      Text(`正确答案：${Review.correctOptionLetter(question)}  ${question.answer}`)
        .fontSize(KFont.meta())
        .lineHeight(KLine.normal())
        .fontColor(KColor.primaryText())
        .margin({ top: KSpace.XS })
        .width('100%')

      if (question.tags.length > 0) {
        Text(`考点：${question.tags.join(' · ')}`)
          .fontSize(KFont.meta())
          .fontColor(KColor.ink())
          .margin({ top: KSpace.S })
          .width('100%')
      }

      Text('四个选项都出自同一批官方表述，区别在于各自回答的是哪个问题——按题干问的「角度」去对，不要按熟悉度选。')
        .fontSize(KFont.caption())
        .lineHeight(KLine.tight())
        .fontColor(KColor.sub())
        .margin({ top: KSpace.S })
        .width('100%')

      Text('逐项详解待内容管道为卡片生成 explain 字段后补上。')
        .fontSize(KFont.caption())
        .fontColor(KColor.mut())
        .margin({ top: KSpace.XS })
        .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(KSpace.L)
    .margin({ top: KSpace.M })
    .backgroundColor(KColor.surfaceAlt())
    .borderRadius(KRadius.L)
  }

  @Builder
  choiceFlow(question: QuizCard) {
    ForEach(question.options, (choice: Choice, optionIndex: number) => {
      this.optionRow(choice, optionIndex)
    }, (choice: Choice) => `${question.id}-${choice.text}`)

    if (this.answered >= 0) {
      this.explainBlock(question)
      this.actionBar()
    } else {
      Text('选出正确的一项')
        .fontSize(KFont.caption())
        .fontColor(KColor.mut())
        .width('100%')
        .margin({ top: KSpace.XL })
    }
  }

  @Builder
  selfReviewFlow(question: QuizCard) {
    Text('这道题暂无合格选项，改为自评')
      .fontSize(KFont.caption())
      .fontColor(KColor.mut())
      .width('100%')
      .margin({ top: KSpace.M })

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
      Text(question.answer)
        .fontSize(KFont.body())
        .lineHeight(KLine.relaxed())
        .fontColor(KColor.ink())
        .width('100%')
        .padding(KSpace.L)
        .margin({ top: KSpace.M })
        .backgroundColor(KColor.surfaceAlt())
        .borderRadius(KRadius.L)

      Row() {
        this.gradeButton('忘了', '10 分钟后', GRADE_FORGOT, false)
        this.gradeButton('想起', '正常间隔', GRADE_RECALLED, true)
        this.gradeButton('太简单', '拉长间隔', GRADE_EASY, false)
      }
      .width('100%')
      .margin({ top: KSpace.XL })
    }
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
        Text(`第 ${this.index + 1} / ${this.quiz.length} 题` + (this.cached ? ' · 离线题库' : ''))
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .width('100%')

        this.questionBlock(this.current()!)

        if (this.fallbackMode) {
          this.selfReviewFlow(this.current()!)
        } else {
          this.choiceFlow(this.current()!)
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
        // Scroll 只允许一个子组件，所以由外层 Column 兜住 ForEach
        Column() {
          // 主题指纹层：字号 / 深色变化时重建（令牌全局读 AppStorage，ArkUI 追踪不到）
          ForEach([`${this.darkMode ? 'd' : 'l'}-${this.fontScale}`], () => {
            this.body()
          }, (key: string) => key)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
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

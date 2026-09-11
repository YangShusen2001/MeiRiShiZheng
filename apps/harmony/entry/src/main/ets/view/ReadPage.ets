import { AiAnnotation, ClippedArticle } from '../model/Content';
import { Ai, AiResult, CODE_AI_ERROR, CODE_NETWORK, CODE_RATE_LIMITED, TermAskResult } from '../service/Ai';
import { Clipboard } from '../service/Clipboard';
import { common } from '@kit.AbilityKit';
import { ContentService, Loaded } from '../service/ContentService';
import { HttpError, STATUS_LOCAL_FAILURE } from '../service/Http';
import { Net } from '../service/Net';
import { Invite, InviteResult } from '../service/Invite';
import { Settings } from '../service/Settings';
import { Terms } from '../service/Terms';
import { Share } from '../service/Share';
import { Speech } from '../service/Speech';
import { annotationBg, KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';
import { annotationLabel, buildReaderSegments, ReaderSegment } from './ReaderSegments';
import { SettingsSheet } from './SettingsSheet';

/** 追问主题长度上限（与后端 `term` 契约一致：min 1 / max 100）。 */
const ASK_TERM_LIMIT: number = 100;

/**
 * 阅读页路由参数。
 * 带上当日文章列表（`dayIds`）而不是只带前/后一篇 id——阅读页据此**连续**翻页，
 * 否则翻一次之后有一侧邻居信息就丢了，连续阅读会断。
 */
export interface ReadParam {
  articleId: string;
  dayIds: string[];
}

/**
 * 阅读页：原文分段渲染 + AI 四色标注（只读）。
 *
 * ## 视觉
 * 全部取自 `theme/Tokens.ets`；页面用 `@StorageLink` 订阅主题与字号，切换后即时重建。
 *
 * ## 交互（相对首版补齐）
 * 1. **释义改底部浮层**——原先插在正文中间，一滚动就跑出视野；整屏遮罩可点收起；
 * 2. **标注总览 + 跳转**——可展开清单，点条目滚到原文段落（List + Scroller）；
 * 3. **标注类型筛选**——点图例切换只看某类；选中态除颜色外**另有加粗**，不靠颜色单独表意；
 * 4. **阅读进度**——底部细进度条 + 百分比；
 * 5. **继续上次阅读**——离开时记位置，再进来顶部给「第 N 段」入口（不自动跳，避免抢滚动）；
 * 6. **上一篇 / 下一篇**——阅读页内连续翻阅，不必退回首页；
 * 7. **复制原文链接**——放在来源行旁边，就在"这是哪来的"上下文里；
 * 8. **离线感知**——区分「没联网」与「服务异常」；
 * 9. **触摸目标**——所有可点元素高度 ≥44vp。
 *
 * ## 关键纪律
 * AI 内容是否可用由 `ContentService.usableAnnotations/usableSummary` 统一门控
 * （`aiStatus !== 'ok'` 一律不渲染），页面不自行判断，避免两处规则漂移。
 *
 * ⚠️ 内联高亮用 `Span.textBackgroundStyle`；若本机 SDK 不支持，删除该行即降级为
 * 「仅文字颜色/字重区分」，其余逻辑不变。
 */
@Component
export struct ReadPage {
  @Consume('navStack') navStack: NavPathStack;
  @Prop articleId: string = '';
  @Prop dayIds: string[] = [];
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;
  @State loading: boolean = true;
  @State errorText: string = '';
  /** 非致命提示（如朗读引擎不可用）：不打断阅读，只说明情况。 */
  @State hintText: string = '';
  @State title: string = '';
  @State metaText: string = '';
  @State url: string = '';
  @State summaryText: string = '';
  @State paragraphs: string[] = [];
  @State annotations: AiAnnotation[] = [];
  /** 空 = 显示全部类型。 */
  @State activeFilters: string[] = [];
  @State overviewOpen: boolean = false;
  @State settingsOpen: boolean = false;
  @State tipVisible: boolean = false;
  @State tipLabel: string = '';
  @State tipText: string = '';
  @State copiedText: string = '';
  @State progress: number = 0;
  @State resumeIndex: number = 0;
  /** 是否已滚过头部。只在**翻转时**改状态，避免滚动中高频重建。 */
  @State scrolledPastHeader: boolean = false;
  /** AI 深挖状态。 */
  @State aiRequested: boolean = false;
  @State aiLoading: boolean = false;
  @State aiOk: boolean = false;
  @State aiText: string = '';
  @State aiCode: string = '';
  /** 术语追问状态。 */
  @State askRequested: boolean = false;
  @State askLoading: boolean = false;
  @State askSuggestions: string[] = [];
  @State askAnswer: string = '';
  @State askInput: string = '';
  @State askError: string = '';
  @State askCode: string = '';
  /** 当前片段是否已收藏（每次换片段重置）。 */
  @State termSaved: boolean = false;
  /** 邀请码激活（AI 额度）。 */
  @State inviteInput: string = '';
  @State inviteBusy: boolean = false;
  @State inviteMsg: string = '';
  @State inviteOk: boolean = false;
  /** 本篇是否来自本地缓存（离线可读已看过的文章）。 */
  @State showingCache: boolean = false;
  /** 朗读状态（由朗读控件的 stateChange 事件驱动）。 */
  @State speaking: boolean = false;

  /** 触发 AI 的原文片段（与释义分开存，避免两件事混在一起）。 */
  private aiSource: string = '';

  /** 段落列表滚动控制器：标注跳转与续读定位用。 */
  private scroller: Scroller = new Scroller();
  /** 当前顶部段落（滚动中持续更新，仅在离开页面时落盘一次）。 */
  private currentTopIndex: number = 0;

  aboutToAppear(): void {
    // 朗读状态由控件事件驱动（暂停 / 停止 / 播完都会回调），页面不需要自己猜
    Speech.onStateChange((playing: boolean) => {
      this.speaking = playing;
    });
    // 朗读进度落盘：暂停 / 停止 / 播完都会回调，用于"接着听"
    Speech.onProgress((percent: number) => {
      if (this.articleId.length > 0 && percent > 0) {
        Settings.savePlayProgress(this.articleId, percent);
      }
    });
    this.loadArticle();
  }

  /**
   * 按已播放百分比推出起始段（按字数折算）。
   *
   * 控件只回报**整篇的播放百分比**、不回报"读到文本哪一段"，
   * 所以用字数比例折算——对通勤"接着听"够用，且不依赖控件内部实现。
   */
  private paragraphAtPercent(percent: number): number {
    let total: number = 0;
    for (const paragraph of this.paragraphs) {
      total += paragraph.length;
    }
    if (total === 0 || this.paragraphs.length === 0) {
      return 0;
    }
    const target: number = Math.floor(total * percent / 100);
    let acc: number = 0;
    for (let index = 0; index < this.paragraphs.length; index++) {
      acc += this.paragraphs[index].length;
      if (acc >= target) {
        return index;
      }
    }
    return this.paragraphs.length - 1;
  }

  /** 离开时记录阅读位置：一次写入，避免滚动中频繁落盘。 */
  aboutToDisappear(): void {
    // 朗读必须随页面销毁停止，否则返回首页后还在念
    Speech.stop();
    this.speaking = false;
    if (this.paragraphs.length > 0 && this.currentTopIndex > 0) {
      Settings.saveReadingPosition(this.articleId, this.currentTopIndex);
    }
  }

  /**
   * 开始/停止朗读。
   * 从**当前可见段落**开始，而不是从头——通勤时用户往往已经看了前半段，
   * 从头发起等于让他重听一遍。
   */
  private toggleSpeech(): void {
    if (this.speaking) {
      Speech.stop();
      this.speaking = false;
      return;
    }
    const context: common.UIAbilityContext | null = Settings.context();
    if (context === null) {
      this.hintText = '上下文未就绪，无法朗读。';
      return;
    }
    // 起始段：优先"上次听到哪"（持久化的朗读进度），其次当前可见段落。
    // 控件只能从文章开头播，所以先把前面已读的部分截掉——这就是"接着听"的实现。
    const saved: number = Settings.playProgress(this.articleId);
    const resuming: boolean = saved >= 5 && saved <= 95;
    const from: number = resuming
      ? this.paragraphAtPercent(saved)
      : Math.max(0, this.currentTopIndex - 1);
    Speech.ready(context).then((ready: boolean) => {
      if (!ready) {
        this.hintText = '系统朗读控件不可用（仅支持中国境内的手机 / 平板 / PC），无法朗读本篇。';
        return;
      }
      Speech.start(this.title, this.paragraphs, from, this.articleId).then((started: boolean) => {
        if (!started) {
          this.hintText = '朗读启动失败，请稍后重试。';
        } else {
          this.hintText = resuming ? `从上次听到的地方继续（约 ${Math.round(saved)}%）。` : '';
        }
      });
    });
  }

  private loadArticle(): void {
    this.loading = true;
    this.errorText = '';
    this.tipVisible = false;
    this.overviewOpen = false;
    this.activeFilters = [];
    this.copiedText = '';
    this.progress = 0;
    this.currentTopIndex = 0;
    ContentService.loadArticle(this.articleId)
      .then((loaded: Loaded<ClippedArticle>) => {
        const article: ClippedArticle = loaded.data;
        this.title = article.title;
        this.metaText = `${article.source} · ${article.date}`;
        this.url = article.url;
        this.summaryText = ContentService.usableSummary(article);
        this.paragraphs = article.paragraphs;
        this.annotations = ContentService.usableAnnotations(article);
        // 仅当记录的就是本篇时才提示续读
        this.resumeIndex = Settings.lastReadId() === this.articleId ? Settings.lastReadIndex() : 0;
        this.showingCache = loaded.cached;
        this.loading = false;
      })
      .catch((err: Error) => {
        this.report(err);
      });
  }

  private report(err: Error): void {
    Net.probe().then((online: boolean) => {
      this.errorText = ReadPage.describe(err, online);
      this.loading = false;
    });
  }

  private static describe(err: Error, online: boolean): string {
    if (err instanceof HttpError) {
      if (err.status === STATUS_LOCAL_FAILURE) {
        return err.message;
      }
      if (err.status === 404) {
        return '找不到这篇原文（可能内容通道尚未部署，或文章 id 已失效）。';
      }
      return `请求失败：HTTP ${err.status}`;
    }
    if (!online) {
      return '当前设备没有网络连接。请检查网络后重试。';
    }
    return `网络异常：${err.message}`;
  }

  private static explanationOf(annotation: AiAnnotation): string {
    const value: string | undefined = annotation.explanation;
    return value === undefined ? '' : value;
  }

  private countOf(type: string): number {
    let total: number = 0;
    for (const item of this.annotations) {
      if (item.type === type) {
        total = total + 1;
      }
    }
    return total;
  }

  /** 当前要渲染的标注：未选筛选 = 全部；已选 = 只含选中类型。 */
  private visibleAnnotations(): AiAnnotation[] {
    if (this.activeFilters.length === 0) {
      return this.annotations;
    }
    return this.annotations.filter((item: AiAnnotation) => this.activeFilters.indexOf(item.type) >= 0);
  }

  private isTypeActive(type: string): boolean {
    return this.activeFilters.length === 0 || this.activeFilters.indexOf(type) >= 0;
  }

  /** 切换某类标注的筛选；全部类型都被选满时回到"全部"。 */
  private toggleFilter(type: string): void {
    if (this.activeFilters.length === 0) {
      this.activeFilters = [type];
      return;
    }
    const next: string[] = this.activeFilters.filter((item: string) => item !== type);
    if (next.length === this.activeFilters.length) {
      next.push(type);
    }
    this.activeFilters = next.length >= 4 ? [] : next;
  }

  private neighbourId(offset: number): string {
    const index: number = this.dayIds.indexOf(this.articleId);
    if (index < 0) {
      return '';
    }
    const target: number = index + offset;
    if (target < 0 || target >= this.dayIds.length) {
      return '';
    }
    return this.dayIds[target];
  }

  /** 翻到相邻文章：用 replace 保持栈深不变，避免越读越深的返回栈。 */
  private openNeighbour(offset: number): void {
    const target: string = this.neighbourId(offset);
    if (target.length === 0) {
      return;
    }
    const param: ReadParam = { articleId: target, dayIds: this.dayIds };
    this.navStack.replacePathByName('read', param);
  }

  private showExplanation(segment: ReaderSegment): void {
    this.tipLabel = annotationLabel(segment.type);
    // 不伪造释义：生成失败时如实说明。
    this.tipText = segment.explanation.length > 0
      ? segment.explanation
      : `${segment.text}（本篇未生成释义）`;
    // 换片段时重置 AI 结果，避免上一段的解释残留造成误读
    this.aiSource = segment.text;
    this.aiRequested = false;
    this.aiLoading = false;
    this.aiOk = false;
    this.aiText = '';
    this.aiCode = '';
    // 追问同理：建议问题与回答都是"针对上一段的"，留着会张冠李戴
    this.askRequested = false;
    this.askLoading = false;
    this.askSuggestions = [];
    this.askAnswer = '';
    this.askInput = '';
    this.askError = '';
    this.askCode = '';
    this.termSaved = Terms.has(segment.text);
    this.tipVisible = true;
  }

  /** 对当前片段发起 AI 深挖（走 Worker，密钥不落客户端）。 */
  private runAi(): void {
    if (this.aiLoading || this.aiSource.length === 0) {
      return;
    }
    this.aiRequested = true;
    this.aiLoading = true;
    this.aiOk = false;
    this.aiText = '';
    this.aiCode = '';
    Ai.explain(this.aiSource).then((result: AiResult) => {
      this.aiLoading = false;
      this.aiOk = result.ok;
      this.aiText = result.text;
      this.aiCode = result.code;
    });
  }

  /**
   * 只有"等一会儿就会好"的原因才给重试按钮。
   * 邀请码/配额/未配置密钥这三种，重试一百次也一样——给重试按钮反而误导。
   */
  /**
   * 追问用的主题文本：后端 `term` 限长 100 字。
   * **超长时不给追问入口而不是截断**——截断会改变语义，问出来的答案会跑偏。
   */
  private askTermText(): string {
    const source: string = this.aiSource.trim();
    return source.length <= ASK_TERM_LIMIT ? source : '';
  }

  /**
   * 拉「建议问题」。
   *
   * **只在用户主动点「问点什么」时才花额度**：服务端是邀请码额度 + 10 次/分钟限流，
   * AI 深挖已经花掉一次，再自动追问一次等于每次都双花——额度是用户的稀缺资源，
   * 不该替他花掉。
   */
  private loadSuggestions(): void {
    const term: string = this.askTermText();
    if (term.length === 0 || this.askLoading) {
      return;
    }
    this.askRequested = true;
    this.askLoading = true;
    this.askError = '';
    Ai.askTerm(term, this.aiText, '').then((result: TermAskResult) => {
      this.askLoading = false;
      if (result.ok) {
        this.askSuggestions = result.suggestions;
      } else {
        this.askCode = result.code;
        this.askError = result.text;
      }
    });
  }

  /**
   * 收藏当前片段为术语。
   *
   * 把已知的 AI 解析一并存下——用户在浮层里已经花额度拿到的东西，
   * 不该在「我的术语」里再花一次。
   */
  private saveTerm(): void {
    const text: string = this.aiSource.trim();
    if (text.length === 0 || this.termSaved) {
      return;
    }
    Terms.save({
      text: text,
      articleId: this.articleId,
      note: '',
      explanation: this.aiOk ? this.aiText : '',
      savedAt: Date.now(),
    });
    this.termSaved = true;
  }

  /** 就某个问题追问（点建议问题，或自己输入）。 */
  private ask(question: string): void {
    const term: string = this.askTermText();
    const asked: string = question.trim();
    if (term.length === 0 || asked.length === 0 || this.askLoading) {
      return;
    }
    this.askLoading = true;
    this.askError = '';
    this.askAnswer = '';
    Ai.askTerm(term, this.aiText, asked).then((result: TermAskResult) => {
      this.askLoading = false;
      if (result.ok) {
        this.askAnswer = result.answer;
        this.askInput = '';
      } else {
        this.askCode = result.code;
        this.askError = result.text;
      }
    });
  }

  private aiRetryable(): boolean {    return this.aiCode === '' || this.aiCode === CODE_RATE_LIMITED
      || this.aiCode === CODE_AI_ERROR || this.aiCode === CODE_NETWORK;
  }

  /** 跳到指定段落（列表第 0 项是头部信息，正文段自 1 起）。 */
  private scrollToParagraph(paragraphIndex: number): void {
    this.scroller.scrollToIndex(paragraphIndex + 1, true);
  }

  private jumpTo(annotation: AiAnnotation): void {
    this.overviewOpen = false;
    this.scrollToParagraph(annotation.paragraphIndex);
  }

  private copyLink(): void {
    if (this.url.length === 0) {
      return;
    }
    Clipboard.copyText(this.url).then((ok: boolean) => {
      this.copiedText = ok ? '已复制' : '复制失败';
      setTimeout(() => {
        this.copiedText = '';
      }, 2000);
    });
  }

  /** 系统分享。拉不起来时退回复制链接——按钮点了没反应是最糟的结果。 */
  private shareArticle(): void {
    if (this.url.length === 0) {
      return;
    }
    Share.shareText(this.title, this.url).then((shown: boolean) => {
      if (!shown) {
        this.copyLink();
      }
    });
  }

  // —— 图例（同时是筛选器）——
  @Builder
  legendChip(label: string, type: string) {
    Text(`${label} ${this.countOf(type)}`)
      .fontSize(KFont.caption())
      .fontWeight(this.isTypeActive(type) ? FontWeight.Bold : FontWeight.Normal)
      .fontColor(this.isTypeActive(type) ? KColor.annInk() : KColor.mut())
      .backgroundColor(this.isTypeActive(type) ? annotationBg(type) : KColor.surface())
      .borderRadius(KRadius.S)
      .borderWidth(1)
      .borderColor(this.isTypeActive(type) ? KColor.lineSoft() : KColor.line())
      .height(KSize.TOUCH_MIN)
      .padding({ left: KSpace.M, right: KSpace.M })
      .margin({ right: KSpace.S, top: KSpace.S })
      .textAlign(TextAlign.Center)
      .onClick(() => {
        this.toggleFilter(type);
      })
  }

  /** 取消筛选。 */
  @Builder
  clearFilterChip() {
    Text('全部')
      .fontSize(KFont.caption())
      .fontColor(KColor.primaryText())
      .backgroundColor(KColor.primarySoft())
      .borderRadius(KRadius.S)
      .height(KSize.TOUCH_MIN)
      .padding({ left: KSpace.M, right: KSpace.M })
      .margin({ right: KSpace.S, top: KSpace.S })
      .textAlign(TextAlign.Center)
      .onClick(() => {
        this.activeFilters = [];
      })
  }

  /** 标注总览：逐条列出类型、原文片段与释义，点条目跳到原文。 */
  @Builder
  overviewPanel() {
    Column() {
      ForEach(this.visibleAnnotations(), (annotation: AiAnnotation) => {
        Column() {
          Row() {
            Text(annotationLabel(annotation.type))
              .fontSize(KFont.caption())
              .fontColor(KColor.annInk())
              .backgroundColor(annotationBg(annotation.type))
              .borderRadius(KRadius.XS)
              .padding({ left: KSpace.S, right: KSpace.S, top: KSpace.HAIR, bottom: KSpace.HAIR })
            Text(`第 ${annotation.paragraphIndex + 1} 段`)
              .fontSize(KFont.caption())
              .fontColor(KColor.mut())
              .margin({ left: KSpace.S })
          }
          .width('100%')
          Text(annotation.text)
            .fontSize(KFont.meta())
            .lineHeight(KLine.tight())
            .fontColor(KColor.ink())
            .margin({ top: KSpace.XS })
            .width('100%')
          if (ReadPage.explanationOf(annotation).length > 0) {
            Text(ReadPage.explanationOf(annotation))
              .fontSize(KFont.caption())
              .lineHeight(KLine.tight())
              .fontColor(KColor.sub())
              .margin({ top: KSpace.XS })
              .width('100%')
          }
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .constraintSize({ minHeight: KSize.TOUCH_MIN })
        .padding({ top: KSpace.M, bottom: KSpace.M })
        .onClick(() => {
          this.jumpTo(annotation);
        })
      }, (annotation: AiAnnotation) => `${annotation.id}-${this.activeFilters.length}`)
    }
    .width('100%')
    .padding(KSpace.L)
    .margin({ top: KSpace.S })
    .backgroundColor(KColor.surfaceAlt())
    .borderRadius(KRadius.L)
  }

  @Builder
  headerBlock() {
    Column() {
      Row() {
        Text(this.metaText)
          .fontSize(KFont.meta())
          .fontColor(KColor.sub())
          .layoutWeight(1)
        Text(this.copiedText.length > 0 ? this.copiedText : '复制')
          .fontSize(KFont.caption())
          .fontColor(this.copiedText.length > 0 ? KColor.primaryText() : KColor.mut())
          .height(KSize.TOUCH_MIN)
          .padding({ left: KSpace.S, right: KSpace.S })
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.copyLink();
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (this.showingCache) {
        Text('离线内容：本篇来自本地缓存')
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .margin({ top: KSpace.XS })
      }

      if (this.hintText.length > 0) {
        Text(this.hintText)
          .fontSize(KFont.caption())
          .fontColor(KColor.warnInk())
          .backgroundColor(KColor.warnSoft())
          .borderRadius(KRadius.S)
          .padding(KSpace.S)
          .width('100%')
          .margin({ top: KSpace.S })
      }

      Text(this.title)
        .fontSize(KFont.titleL())
        .fontWeight(FontWeight.Bold)
        .fontColor(KColor.ink())
        .lineHeight(KLine.display())
        .margin({ top: KSpace.S })
        .width('100%')

      if (this.resumeIndex > 0 && this.paragraphs.length > 0) {
        Text(`继续上次阅读（第 ${this.resumeIndex + 1} 段）`)
          .fontSize(KFont.meta())
          .fontColor(KColor.primaryText())
          .backgroundColor(KColor.primarySoft())
          .borderRadius(KRadius.S)
          .padding({ left: KSpace.M, right: KSpace.M })
          .height(KSize.TOUCH_MIN)
          .textAlign(TextAlign.Center)
          .margin({ top: KSpace.M })
          .onClick(() => {
            this.scrollToParagraph(this.resumeIndex);
          })
      }

      if (this.summaryText.length > 0) {
        Column() {
          Text('AI 概括')
            .fontSize(KFont.caption())
            .fontColor(KColor.sub())
          Text(this.summaryText)
            .fontSize(KFont.body())
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
      }

      if (this.annotations.length > 0) {
        Row() {
          Text(`已读 ${Math.round(this.progress * 100)}%`)
            .fontSize(KFont.caption())
            .fontColor(KColor.mut())
            .layoutWeight(1)
          Text(this.speaking ? '停止' : '听')
            .fontSize(KFont.caption())
            .fontWeight(this.speaking ? FontWeight.Bold : FontWeight.Normal)
            .fontColor(this.speaking ? KColor.primaryText() : KColor.sub())
            .height(KSize.TOUCH_MIN)
            .padding({ left: KSpace.S, right: KSpace.S })
            .textAlign(TextAlign.Center)
            .onClick(() => {
              this.toggleSpeech();
            })
          Text('分享')
            .fontSize(KFont.caption())
            .fontColor(KColor.sub())
            .height(KSize.TOUCH_MIN)
            .padding({ left: KSpace.S, right: KSpace.S })
            .textAlign(TextAlign.Center)
            .onClick(() => {
              this.shareArticle();
            })
          Text(this.overviewOpen ? '收起' : '清单')
            .fontSize(KFont.caption())
            .fontColor(KColor.primaryText())
            .height(KSize.TOUCH_MIN)
            .padding({ left: KSpace.S, right: KSpace.S })
            .textAlign(TextAlign.Center)
            .onClick(() => {
              this.overviewOpen = !this.overviewOpen;
            })
          Text('Aa')
            .fontSize(KFont.meta())
            .fontColor(KColor.sub())
            .height(KSize.TOUCH_MIN)
            .padding({ left: KSpace.S, right: KSpace.S })
            .textAlign(TextAlign.Center)
            .onClick(() => {
              this.tipVisible = false;
              this.settingsOpen = true;
            })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: KSpace.M })

        Flex({ wrap: FlexWrap.Wrap }) {
          if (this.activeFilters.length > 0) {
            this.clearFilterChip()
          }
          if (this.countOf('exam_point') > 0) {
            this.legendChip('考点', 'exam_point')
          }
          if (this.countOf('viewpoint') > 0) {
            this.legendChip('观点', 'viewpoint')
          }
          if (this.countOf('term') > 0) {
            this.legendChip('术语', 'term')
          }
          if (this.countOf('figure') > 0) {
            this.legendChip('数字指标', 'figure')
          }
        }
        .width('100%')

        if (this.overviewOpen) {
          this.overviewPanel()
        }
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  @Builder
  paragraphBlock(paragraphIndex: number) {
    Text() {
      ForEach(
        buildReaderSegments(this.paragraphs[paragraphIndex], this.visibleAnnotations(), paragraphIndex),
        (segment: ReaderSegment) => {
          if (segment.type.length === 0) {
            Span(segment.text)
          } else {
            Span(segment.text)
              .fontColor(KColor.annInk())
              .fontWeight(FontWeight.Medium)
              .textBackgroundStyle({ color: annotationBg(segment.type) })
              .onClick(() => {
                this.showExplanation(segment);
              })
          }
        },
        (segment: ReaderSegment, index: number) => `${paragraphIndex}-${index}-${segment.type}`,
      )
    }
    .fontSize(KFont.body())
    .lineHeight(KLine.relaxed())
    .fontColor(KColor.ink())
    .width('100%')
  }

  /** 篇间翻阅：不退回首页即可连续读。 */
  @Builder
  neighbourBar() {
    Row() {
      if (this.neighbourId(-1).length > 0) {
        Text('‹ 上一篇')
          .fontSize(KFont.meta())
          .fontColor(KColor.primaryText())
          .backgroundColor(KColor.surface())
          .borderRadius(KRadius.S)
          .height(KSize.TOUCH_MIN)
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
          .margin({ right: KSpace.S })
          .onClick(() => {
            this.openNeighbour(-1);
          })
      }
      if (this.neighbourId(1).length > 0) {
        Text('下一篇 ›')
          .fontSize(KFont.meta())
          .fontColor(KColor.primaryText())
          .backgroundColor(KColor.surface())
          .borderRadius(KRadius.S)
          .height(KSize.TOUCH_MIN)
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
          .margin({ left: KSpace.S })
          .onClick(() => {
            this.openNeighbour(1);
          })
      }
    }
    .width('100%')
    .margin({ top: KSpace.XXL })
  }

  /**
   * 激活邀请码。成功后**自动接着发起 AI 解析**——
   * 让用户再点一次「AI 深挖」是多余的一步，意图已经明确。
   */
  private activateInvite(): void {
    if (this.inviteBusy) {
      return;
    }
    this.inviteBusy = true;
    this.inviteMsg = '';
    Invite.activate(this.inviteInput).then((result: InviteResult) => {
      this.inviteBusy = false;
      this.inviteOk = result.ok;
      this.inviteMsg = result.text;
      if (result.ok) {
        this.runAi();
      }
    });
  }

  /** 邀请码入口：只在「缺码 / 额度用尽」时出现，其他错误摆出来只会误导。 */
  @Builder
  inviteBlock() {
    Column() {
      Text('填写邀请码即可启用 AI 解析')
        .fontSize(KFont.caption())
        .fontColor(KColor.sub())
        .width('100%')
      Row() {
        TextInput({ text: this.inviteInput, placeholder: '请输入邀请码' })
          .fontSize(KFont.meta())
          .height(KSize.TOUCH_MIN)
          .layoutWeight(1)
          .backgroundColor(KColor.surfaceAlt())
          .borderRadius(KRadius.S)
          .onChange((value: string) => {
            this.inviteInput = value;
          })
        Text(this.inviteBusy ? '激活中…' : '激活')
          .fontSize(KFont.meta())
          .fontColor(KColor.surface())
          .backgroundColor(KColor.primary())
          .borderRadius(KRadius.S)
          .height(KSize.TOUCH_MIN)
          .padding({ left: KSpace.L, right: KSpace.L })
          .textAlign(TextAlign.Center)
          .margin({ left: KSpace.S })
          .onClick(() => {
            this.activateInvite();
          })
      }
      .width('100%')
      .margin({ top: KSpace.S })

      if (this.inviteMsg.length > 0) {
        Text(this.inviteMsg)
          .fontSize(KFont.caption())
          .lineHeight(KLine.tight())
          .fontColor(this.inviteOk ? KColor.primaryText() : KColor.warnInk())
          .width('100%')
          .margin({ top: KSpace.S })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .margin({ top: KSpace.S })
  }

  /**
   * 建议问题（点一下就问）。
   * 用 chip 而不是列表：问题是短句、数量 ≤3，chip 更省竖向空间，也更像"可选动作"。
   */
  @Builder
  suggestionChip(question: string) {
    Text(question)
      .fontSize(KFont.caption())
      .lineHeight(KLine.tight())
      .fontColor(KColor.primaryText())
      .backgroundColor(KColor.primarySoft())
      .borderRadius(KRadius.S)
      .padding({ left: KSpace.M, right: KSpace.M, top: KSpace.S, bottom: KSpace.S })
      .margin({ right: KSpace.S, top: KSpace.S })
      .onClick(() => {
        this.ask(question);
      })
  }

  /**
   * 术语追问区块（嵌在 AI 解析之下）。
   *
   * ## 为什么先给"建议问题"而不是直接摆输入框
   * 空输入框会让人**不知道从何问起**；给出几个能点的具体问题，
   * 用户立刻知道"原来还能这样问"。移动端也少打字。
   *
   * ## 四种状态都要有去处
   * 未开始（一个明确按钮）→ 加载中（说明在做什么）→ 有结果（chips + 自由输入 + 回答）
   * → 失败（原话 + 可重试）。**不留空白态**，否则用户会以为卡住了。
   *
   * ## 片段过长时不给入口
   * 后端 `term` 限 100 字，超长就说明原因、不给按钮——**不截断**（截断会改变语义）。
   */
  @Builder
  askBlock() {
    Column() {
      if (this.askTermText().length === 0) {
        Text('这段较长，暂不支持追问——换一段更短的文字再试。')
          .fontSize(KFont.caption())
          .lineHeight(KLine.tight())
          .fontColor(KColor.mut())
          .margin({ top: KSpace.M })
          .width('100%')
      } else {
        Divider()
          .color(KColor.lineSoft())
          .margin({ top: KSpace.M, bottom: KSpace.M })

        if (this.askAnswer.length > 0) {
          Text('AI 回答')
            .fontSize(KFont.caption())
            .fontColor(KColor.sub())
          Text(this.askAnswer)
            .fontSize(KFont.meta())
            .lineHeight(KLine.tight())
            .fontColor(KColor.ink())
            .margin({ top: KSpace.XS })
            .width('100%')
        }

        if (this.askLoading) {
          Row() {
            LoadingProgress().width(20).height(20)
            Text(this.askAnswer.length > 0 ? 'AI 正在回答…' : 'AI 正在想可以问什么…')
              .fontSize(KFont.meta())
              .fontColor(KColor.sub())
              .margin({ left: KSpace.S })
          }
          .width('100%')
          .height(KSize.TOUCH_MIN)
          .alignItems(VerticalAlign.Center)
          .margin({ top: KSpace.S })
        } else {
          if (this.askError.length > 0) {
            Text(this.askError)
              .fontSize(KFont.caption())
              .lineHeight(KLine.tight())
              .fontColor(KColor.warnInk())
              .margin({ top: KSpace.S })
              .width('100%')
          }

          if (!this.askRequested) {
            Text('问点什么（AI 帮你想）')
              .fontSize(KFont.meta())
              .fontWeight(FontWeight.Medium)
              .fontColor(KColor.primaryText())
              .backgroundColor(KColor.surfaceAlt())
              .borderRadius(KRadius.S)
              .height(KSize.TOUCH_MIN)
              .width('100%')
              .textAlign(TextAlign.Center)
              .margin({ top: KSpace.S })
              .onClick(() => {
                this.loadSuggestions();
              })
          } else {
            if (this.askSuggestions.length > 0) {
              Flex({ wrap: FlexWrap.Wrap }) {
                ForEach(this.askSuggestions, (question: string) => {
                  this.suggestionChip(question)
                }, (question: string) => question)
              }
              .width('100%')
            }

            Row() {
              TextInput({ text: this.askInput, placeholder: '也可以自己问…' })
                .layoutWeight(1)
                .height(KSize.TOUCH_MIN)
                .fontSize(KFont.meta())
                .fontColor(KColor.ink())
                .placeholderColor(KColor.mut())
                .backgroundColor(KColor.surface())
                .borderRadius(KRadius.S)
                .onChange((value: string) => {
                  this.askInput = value;
                })

              // 输入为空时降透明度而非隐藏：位置稳定，用户知道"填了就能点"
              Text('问')
                .fontSize(KFont.meta())
                .fontWeight(FontWeight.Medium)
                .fontColor(KColor.surface())
                .backgroundColor(KColor.primary())
                .borderRadius(KRadius.S)
                .height(KSize.TOUCH_MIN)
                .padding({ left: KSpace.XL, right: KSpace.XL })
                .textAlign(TextAlign.Center)
                .margin({ left: KSpace.S })
                .opacity(this.askInput.trim().length === 0 ? 0.4 : 1)
                .enabled(this.askInput.trim().length > 0)
                .onClick(() => {
                  this.ask(this.askInput);
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            .margin({ top: KSpace.S })
          }
        }
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
  }

  /**
   * AI 深挖区块（嵌在释义浮层里）。
   * 复用释义浮层而不是另开入口：用户读释义时正是最想追问的时刻。
   */
  @Builder
  aiBlock() {
    Column() {
      Divider()
        .color(KColor.lineSoft())
        .margin({ top: KSpace.M, bottom: KSpace.M })

      if (!this.aiRequested) {
        Text('AI 深挖这句')
          .fontSize(KFont.meta())
          .fontWeight(FontWeight.Medium)
          .fontColor(KColor.surface())
          .backgroundColor(KColor.primary())
          .borderRadius(KRadius.S)
          .height(KSize.TOUCH_MIN)
          .width('100%')
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.runAi();
          })
      } else if (this.aiLoading) {
        Row() {
          LoadingProgress().width(20).height(20)
          Text('AI 正在解析…')
            .fontSize(KFont.meta())
            .fontColor(KColor.sub())
            .margin({ left: KSpace.S })
        }
        .width('100%')
        .height(KSize.TOUCH_MIN)
        .alignItems(VerticalAlign.Center)
      } else if (this.aiOk) {
        Column() {
          Text('AI 解析')
            .fontSize(KFont.caption())
            .fontColor(KColor.sub())
          Text(this.aiText)
            .fontSize(KFont.meta())
            .lineHeight(KLine.tight())
            .fontColor(KColor.ink())
            .margin({ top: KSpace.XS })
            .width('100%')
          // 收藏：把这段连同**已经拿到的解析**一起存进「我的术语」——
          // 用户已经花过额度的东西，不该在收藏夹里再花一次。
          Text(this.termSaved ? '✓ 已收藏' : '收藏到我的术语')
            .fontSize(KFont.caption())
            .fontColor(this.termSaved ? KColor.mut() : KColor.primaryText())
            .backgroundColor(this.termSaved ? KColor.surface() : KColor.primarySoft())
            .borderRadius(KRadius.S)
            .height(KSize.TOUCH_MIN)
            .padding({ left: KSpace.L, right: KSpace.L })
            .margin({ top: KSpace.S })
            .textAlign(TextAlign.Center)
            .enabled(!this.termSaved)
            .onClick(() => {
              this.saveTerm();
            })
          this.askBlock()
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
      } else {
        Column() {
          Text(this.aiText)
            .fontSize(KFont.meta())
            .lineHeight(KLine.tight())
            .fontColor(KColor.warnInk())
            .width('100%')
          if (this.aiRetryable()) {
            Text('重试')
              .fontSize(KFont.meta())
              .fontColor(KColor.primaryText())
              .backgroundColor(KColor.surfaceAlt())
              .borderRadius(KRadius.S)
              .height(KSize.TOUCH_MIN)
              .width('100%')
              .textAlign(TextAlign.Center)
              .margin({ top: KSpace.S })
              .onClick(() => {
                this.runAi();
              })
          }
          if (Ai.needsInvite(this.aiCode)) {
            this.inviteBlock()
          }
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding(KSpace.M)
        .backgroundColor(KColor.surface())
        .borderRadius(KRadius.S)
      }
    }
    .width('100%')
  }

  /** 底部释义浮层：整屏遮罩可点关闭。 */
  @Builder
  tipSheet() {
    Column() {
      Row() {
        Text(this.tipLabel)
          .fontSize(KFont.caption())
          .fontColor(KColor.ink())
          .backgroundColor(KColor.neutralSoft())
          .borderRadius(KRadius.XS)
          .padding({ left: KSpace.S, right: KSpace.S, top: KSpace.HAIR, bottom: KSpace.HAIR })
        Blank()
        Text('关闭')
          .fontSize(KFont.meta())
          .fontColor(KColor.sub())
          .height(KSize.TOUCH_MIN)
          .padding({ left: KSpace.M, right: KSpace.M })
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.tipVisible = false;
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.tipText)
        .fontSize(KFont.body())
        .lineHeight(KLine.normal())
        .fontColor(KColor.ink())
        .margin({ top: KSpace.S })
        .width('100%')

      this.aiBlock()
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: KSpace.L, right: KSpace.L, top: KSpace.M, bottom: KSpace.XXL })
    .backgroundColor(KColor.hintSoft())
    .borderRadius({ topLeft: KRadius.XL, topRight: KRadius.XL })
    // 入场动效必须加在 @Builder 的根节点上——@Builder 调用返回 void，不能链式调用属性
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 60 })))
  }

  @Builder
  errorCard() {
    Column() {
      Text('无法加载原文')
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
          this.loadArticle();
        })
    }
    .width('100%')
    .padding(KSpace.XXL)
    .margin({ top: KSpace.XXXL })
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
  }

  build() {
    NavDestination() {
      Stack({ alignContent: Alignment.Bottom }) {
        if (this.loading) {
          Row() {
            LoadingProgress().width(28).height(28)
            Text('正在读取原文…')
              .fontSize(KFont.meta())
              .fontColor(KColor.sub())
              .margin({ left: KSpace.M })
          }
          .margin({ top: KSpace.XXXL })
        } else if (this.errorText.length > 0) {
          Column() {
            this.errorCard()
          }
          .width('100%')
          .padding({ left: KSpace.PAGE, right: KSpace.PAGE })
        } else {
          // 主题指纹层：字号 / 深色变化时整层重建，令牌随之重新取值。
          // ArkUI 追踪不到"全局读 AppStorage"的令牌，只订阅状态变量不会重绘（详见 HomePage）。
          ForEach([`${this.darkMode ? 'd' : 'l'}-${this.fontScale}`], () => {
            List({ scroller: this.scroller, space: KSpace.XL }) {
            // 第 0 项为头部（标题 / AI 概括 / 图例 / 标注清单），正文段自 1 起。
            ListItem() {
              this.headerBlock()
            }
            ForEach(this.paragraphs, (paragraph: string, index: number) => {
              ListItem() {
                this.paragraphBlock(index)
              }
            }, (paragraph: string, index: number) => `${index}-${paragraph.length}`)
            ListItem() {
              this.neighbourBar()
            }
          }
          .width('100%')
          .layoutWeight(1)
          .scrollBar(BarState.Off)
          .padding({ left: KSpace.PAGE, right: KSpace.PAGE, top: KSpace.M, bottom: KSpace.XXL })
          .onScrollIndex((first: number, last: number) => {
            this.currentTopIndex = first;
            // 只在"越过头部"这一状态翻转时改 @State，避免滚动中高频重建
            const past: boolean = first > 0;
            if (past !== this.scrolledPastHeader) {
              this.scrolledPastHeader = past;
            }
            const total: number = this.paragraphs.length + 1;
            this.progress = last >= total - 1 ? 1 : (last + 1) / total;
          })
          }, (key: string) => key)
        }

        // 底部阅读进度条：轨道 + 填充（最底层，浮层会盖住它）
        Row() {
          Column()
            .width(`${Math.max(2, Math.round(this.progress * 100))}%`)
            .height(3)
            .backgroundColor(KColor.primary())
        }
        .width('100%')
        .height(3)
        .backgroundColor(KColor.lineSoft())

        if (this.tipVisible) {
          // 遮罩：点击空白处收起
          Column()
            .width('100%')
            .height('100%')
            .backgroundColor(KColor.scrim())
            .transition(TransitionEffect.OPACITY)
            .onClick(() => {
              this.tipVisible = false;
            })
          this.tipSheet()
        }

        if (this.settingsOpen) {
          Column()
            .width('100%')
            .height('100%')
            .backgroundColor(KColor.scrim())
            .transition(TransitionEffect.OPACITY)
            .onClick(() => {
              this.settingsOpen = false;
            })
          SettingsSheet({
            onClose: () => {
              this.settingsOpen = false;
            },
          })
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(KColor.bg())
    }
    // 滚过头部后标题栏显示文章标题：起到「吸顶」的定位作用，
    // 又不占用本就紧张的阅读高度（比真吸顶更适合长文）。
    .title(this.scrolledPastHeader && this.title.length > 0 ? this.title : '阅读')
    .backgroundColor(KColor.bg())
  }
}

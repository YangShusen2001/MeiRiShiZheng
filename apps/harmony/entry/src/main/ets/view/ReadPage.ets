import { AiAnnotation, ClippedArticle } from '../model/Content';
import { Clipboard } from '../service/Clipboard';
import { ContentService } from '../service/ContentService';
import { HttpError, STATUS_LOCAL_FAILURE } from '../service/Http';
import { Net } from '../service/Net';
import { Settings } from '../service/Settings';
import { Share } from '../service/Share';
import { annotationBg, KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';
import { annotationLabel, buildReaderSegments, ReaderSegment } from './ReaderSegments';
import { SettingsSheet } from './SettingsSheet';

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

  /** 段落列表滚动控制器：标注跳转与续读定位用。 */
  private scroller: Scroller = new Scroller();
  /** 当前顶部段落（滚动中持续更新，仅在离开页面时落盘一次）。 */
  private currentTopIndex: number = 0;

  aboutToAppear(): void {
    this.loadArticle();
  }

  /** 离开时记录阅读位置：一次写入，避免滚动中频繁落盘。 */
  aboutToDisappear(): void {
    if (this.paragraphs.length > 0 && this.currentTopIndex > 0) {
      Settings.saveReadingPosition(this.articleId, this.currentTopIndex);
    }
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
      .then((article: ClippedArticle) => {
        this.title = article.title;
        this.metaText = `${article.source} · ${article.date}`;
        this.url = article.url;
        this.summaryText = ContentService.usableSummary(article);
        this.paragraphs = article.paragraphs;
        this.annotations = ContentService.usableAnnotations(article);
        // 仅当记录的就是本篇时才提示续读
        this.resumeIndex = Settings.lastReadId() === this.articleId ? Settings.lastReadIndex() : 0;
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
    this.tipVisible = true;
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
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: KSpace.L, right: KSpace.L, top: KSpace.M, bottom: KSpace.XXL })
    .backgroundColor(KColor.hintSoft())
    .borderRadius({ topLeft: KRadius.XL, topRight: KRadius.XL })
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
            .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 60 })))
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
            .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 60 })))
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

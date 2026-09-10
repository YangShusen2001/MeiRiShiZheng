import { AiAnnotation, ClippedArticle } from '../model/Content';
import { ContentService } from '../service/ContentService';
import { HttpError, STATUS_LOCAL_FAILURE } from '../service/Http';
import { annotationBg, KColor, KFont, KLine, KRadius, KSpace } from '../theme/Tokens';
import { annotationLabel, buildReaderSegments, ReaderSegment } from './ReaderSegments';

/** 阅读页路由参数。 */
export interface ReadParam {
  articleId: string;
}

/**
 * 阅读页：原文分段渲染 + AI 四色标注（只读）。
 *
 * 交互补齐项（相对首版）：
 * 1. **释义改为底部浮层**——首版把释义插在正文中间，一滚动就跑出视野；
 * 2. **点击空白收起**——浮层外整屏可点，符合移动端心智，不必去瞄「关闭」两个字；
 * 3. **标注总览 + 跳转**——首版只能靠滚动找标注；现在可展开清单，点条目直接滚到原文段落；
 * 4. **触摸目标**——图例与清单条目高度 ≥44vp。
 *
 * 关键纪律：AI 内容是否可用由 `ContentService.usableAnnotations/usableSummary` 统一门控
 * （`aiStatus !== 'ok'` 一律不渲染），页面不自行判断，避免两处规则漂移。
 *
 * ⚠️ 渲染实现说明：内联高亮用 `Span.textBackgroundStyle`。
 * 若本机 SDK 不支持该属性，删除该行即可降级为「仅文字颜色/字重区分」，其余逻辑不变。
 */
@Component
export struct ReadPage {
  @Consume('navStack') navStack: NavPathStack;
  @Prop articleId: string = '';
  @State loading: boolean = true;
  @State errorText: string = '';
  @State title: string = '';
  @State metaText: string = '';
  @State summaryText: string = '';
  @State paragraphs: string[] = [];
  @State annotations: AiAnnotation[] = [];
  @State overviewOpen: boolean = false;
  @State tipVisible: boolean = false;
  @State tipLabel: string = '';
  @State tipText: string = '';

  /** 段落列表滚动控制器：用于从标注总览跳转到原文位置。 */
  private scroller: Scroller = new Scroller();

  aboutToAppear(): void {
    this.loadArticle();
  }

  private loadArticle(): void {
    this.loading = true;
    this.errorText = '';
    this.tipVisible = false;
    this.overviewOpen = false;
    ContentService.loadArticle(this.articleId)
      .then((article: ClippedArticle) => {
        this.title = article.title;
        this.metaText = `${article.source} · ${article.date}`;
        this.summaryText = ContentService.usableSummary(article);
        this.paragraphs = article.paragraphs;
        this.annotations = ContentService.usableAnnotations(article);
        this.loading = false;
      })
      .catch((err: Error) => {
        this.errorText = ReadPage.describe(err);
        this.loading = false;
      });
  }

  private static describe(err: Error): string {
    if (err instanceof HttpError) {
      if (err.status === STATUS_LOCAL_FAILURE) {
        return err.message;
      }
      if (err.status === 404) {
        return '找不到这篇原文（可能内容通道尚未部署，或文章 id 已失效）。';
      }
      return `请求失败：HTTP ${err.status}`;
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

  /** 点击正文里的高亮片段：打开底部释义浮层。 */
  private showExplanation(segment: ReaderSegment): void {
    this.tipLabel = annotationLabel(segment.type);
    // 不伪造释义：生成失败时如实说明。
    this.tipText = segment.explanation.length > 0
      ? segment.explanation
      : `${segment.text}（本篇未生成释义）`;
    this.tipVisible = true;
  }

  /** 从标注总览跳到该标注所在段落（列表第 0 项是头部，正文段自 1 起）。 */
  private jumpTo(annotation: AiAnnotation): void {
    this.overviewOpen = false;
    this.scroller.scrollToIndex(annotation.paragraphIndex + 1, true);
  }

  @Builder
  legendChip(label: string, type: string) {
    Text(`${label} ${this.countOf(type)}`)
      .fontSize(KFont.CAPTION)
      .fontColor(KColor.INK)
      .backgroundColor(annotationBg(type))
      .borderRadius(KRadius.S)
      .padding({ left: KSpace.M, right: KSpace.M, top: KSpace.S, bottom: KSpace.S })
      .margin({ right: KSpace.S, top: KSpace.S })
  }

  /** 标注总览：逐条列出类型、原文片段与释义，点条目跳到原文。 */
  @Builder
  overviewPanel() {
    Column() {
      ForEach(this.annotations, (annotation: AiAnnotation) => {
        Column() {
          Row() {
            Text(annotationLabel(annotation.type))
              .fontSize(KFont.CAPTION)
              .fontColor(KColor.INK)
              .backgroundColor(annotationBg(annotation.type))
              .borderRadius(KRadius.XS)
              .padding({ left: KSpace.S, right: KSpace.S, top: KSpace.HAIR, bottom: KSpace.HAIR })
            Text(`第 ${annotation.paragraphIndex + 1} 段`)
              .fontSize(KFont.CAPTION)
              .fontColor(KColor.MUT)
              .margin({ left: KSpace.S })
          }
          .width('100%')
          Text(annotation.text)
            .fontSize(KFont.META)
            .lineHeight(KLine.TIGHT)
            .fontColor(KColor.INK)
            .margin({ top: KSpace.XS })
            .width('100%')
          if (ReadPage.explanationOf(annotation).length > 0) {
            Text(ReadPage.explanationOf(annotation))
              .fontSize(KFont.CAPTION)
              .lineHeight(KLine.TIGHT)
              .fontColor(KColor.SUB)
              .margin({ top: KSpace.XS })
              .width('100%')
          }
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .constraintSize({ minHeight: 44 })
        .padding({ top: KSpace.M, bottom: KSpace.M })
        .onClick(() => {
          this.jumpTo(annotation);
        })
      }, (annotation: AiAnnotation) => annotation.id)
    }
    .width('100%')
    .padding(KSpace.L)
    .margin({ top: KSpace.S })
    .backgroundColor(KColor.SURFACE_ALT)
    .borderRadius(KRadius.L)
  }

  @Builder
  headerBlock() {
    Column() {
      Text(this.metaText)
        .fontSize(KFont.META)
        .fontColor(KColor.SUB)
        .width('100%')
      Text(this.title)
        .fontSize(KFont.TITLE_L)
        .fontWeight(FontWeight.Bold)
        .fontColor(KColor.INK)
        .lineHeight(KLine.DISPLAY)
        .margin({ top: KSpace.S })
        .width('100%')

      if (this.summaryText.length > 0) {
        Column() {
          Text('AI 概括')
            .fontSize(KFont.CAPTION)
            .fontColor(KColor.SUB)
          Text(this.summaryText)
            .fontSize(KFont.BODY)
            .lineHeight(KLine.NORMAL)
            .fontColor(KColor.INK)
            .margin({ top: KSpace.S })
            .width('100%')
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding(KSpace.L)
        .margin({ top: KSpace.M })
        .backgroundColor(KColor.SURFACE)
        .borderRadius(KRadius.L)
      }

      if (this.annotations.length > 0) {
        Row() {
          Flex({ wrap: FlexWrap.Wrap }) {
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
          .layoutWeight(1)

          Text(this.overviewOpen ? '收起清单' : '标注清单')
            .fontSize(KFont.CAPTION)
            .fontColor(KColor.PRIMARY_TEXT)
            .height(44)
            .padding({ left: KSpace.S, right: KSpace.S })
            .textAlign(TextAlign.Center)
            .onClick(() => {
              this.overviewOpen = !this.overviewOpen;
            })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: KSpace.S })

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
        buildReaderSegments(this.paragraphs[paragraphIndex], this.annotations, paragraphIndex),
        (segment: ReaderSegment) => {
          if (segment.type.length === 0) {
            Span(segment.text)
          } else {
            Span(segment.text)
              .fontColor(KColor.INK)
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
    .fontSize(KFont.BODY)
    .lineHeight(KLine.RELAXED)
    .fontColor(KColor.INK)
    .width('100%')
  }

  /** 底部释义浮层：整屏遮罩可点关闭。 */
  @Builder
  tipSheet() {
    Column() {
      Row() {
        Text(this.tipLabel)
          .fontSize(KFont.CAPTION)
          .fontColor(KColor.INK)
          .backgroundColor(KColor.NEUTRAL_SOFT)
          .borderRadius(KRadius.XS)
          .padding({ left: KSpace.S, right: KSpace.S, top: KSpace.HAIR, bottom: KSpace.HAIR })
        Blank()
        Text('关闭')
          .fontSize(KFont.META)
          .fontColor(KColor.SUB)
          .height(44)
          .padding({ left: KSpace.M, right: KSpace.M })
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.tipVisible = false;
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.tipText)
        .fontSize(KFont.BODY)
        .lineHeight(KLine.NORMAL)
        .fontColor(KColor.INK)
        .margin({ top: KSpace.S })
        .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: KSpace.L, right: KSpace.L, top: KSpace.M, bottom: KSpace.XXL })
    .backgroundColor(KColor.HINT_SOFT)
    .borderRadius({ topLeft: KRadius.XL, topRight: KRadius.XL })
  }

  @Builder
  errorCard() {
    Column() {
      Text('无法加载原文')
        .fontSize(KFont.TITLE_S)
        .fontWeight(FontWeight.Bold)
        .fontColor(KColor.DANGER)
      Text(this.errorText)
        .fontSize(KFont.META)
        .lineHeight(KLine.TIGHT)
        .fontColor(KColor.SUB)
        .margin({ top: KSpace.S })
        .textAlign(TextAlign.Center)
      Button('重试')
        .height(44)
        .margin({ top: KSpace.XL })
        .onClick(() => {
          this.loadArticle();
        })
    }
    .width('100%')
    .padding(KSpace.XXL)
    .margin({ top: KSpace.XXXL })
    .backgroundColor(KColor.SURFACE)
    .borderRadius(KRadius.L)
  }

  build() {
    NavDestination() {
      Stack({ alignContent: Alignment.Bottom }) {
        Column() {
          if (this.loading) {
            Row() {
              LoadingProgress().width(28).height(28)
              Text('正在读取原文…')
                .fontSize(KFont.META)
                .fontColor(KColor.SUB)
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
            }
            .width('100%')
            .layoutWeight(1)
            .scrollBar(BarState.Off)
            .padding({ left: KSpace.PAGE, right: KSpace.PAGE, top: KSpace.M, bottom: KSpace.XXL })
          }
        }
        .width('100%')
        .height('100%')
        .alignItems(HorizontalAlign.Start)

        if (this.tipVisible) {
          // 遮罩：点击空白处收起（不必去瞄「关闭」两个字）
          Column()
            .width('100%')
            .height('100%')
            .backgroundColor(KColor.SCRIM)
            .onClick(() => {
              this.tipVisible = false;
            })
          this.tipSheet()
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(KColor.BG)
    }
    .title('阅读')
    .backgroundColor(KColor.BG)
  }
}

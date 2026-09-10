import { AiAnnotation, ClippedArticle } from '../model/Content';
import { ContentService } from '../service/ContentService';
import { HttpError } from '../service/Http';
import { annotationColor, annotationLabel, buildReaderSegments, ReaderSegment } from './ReaderSegments';

/** 阅读页路由参数。 */
export interface ReadParam {
  articleId: string;
}

/**
 * 阅读页：原文分段渲染 + AI 三色标注（只读）。
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
  @State tipVisible: boolean = false;
  @State tipLabel: string = '';
  @State tipText: string = '';

  aboutToAppear(): void {
    this.loadArticle();
  }

  /** 从首页再次进入不同文章时，@Prop 变化需触发重新加载。 */
  onPageShow(): void {
    if (this.title.length === 0 && !this.loading) {
      this.loadArticle();
    }
  }

  private loadArticle(): void {
    this.loading = true;
    this.errorText = '';
    this.tipVisible = false;
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
      if (err.status === 404) {
        return '找不到这篇原文（可能内容通道尚未部署，或文章 id 已失效）。';
      }
      return `请求失败：HTTP ${err.status}`;
    }
    return `网络异常：${err.message}`;
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

  private showExplanation(segment: ReaderSegment): void {
    this.tipLabel = annotationLabel(segment.type);
    // 不伪造释义：生成失败时如实说明。
    this.tipText = segment.explanation.length > 0
      ? segment.explanation
      : `${segment.text}（本篇未生成释义）`;
    this.tipVisible = true;
  }

  @Builder
  legendChip(label: string, type: string) {
    Text(`${label} ${this.countOf(type)}`)
      .fontSize(12)
      .fontColor('#374151')
      .backgroundColor(annotationColor(type))
      .borderRadius(8)
      .padding({ left: 10, right: 10, top: 4, bottom: 4 })
      .margin({ right: 8, top: 8 })
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
              .fontColor('#1F2937')
              .fontWeight(FontWeight.Medium)
              .textBackgroundStyle({ color: annotationColor(segment.type) })
              .onClick(() => {
                this.showExplanation(segment);
              })
          }
        },
        (segment: ReaderSegment, index: number) => `${paragraphIndex}-${index}-${segment.type}`,
      )
    }
    .fontSize(17)
    .lineHeight(30)
    .fontColor('#1F2937')
    .width('100%')
    .margin({ bottom: 18 })
  }

  build() {
    NavDestination() {
      Column() {
        if (this.loading) {
          Row() {
            LoadingProgress().width(28).height(28)
            Text('正在读取原文…').fontSize(14).fontColor('#6B7280').margin({ left: 10 })
          }
          .margin({ top: 60 })
        } else if (this.errorText.length > 0) {
          Column() {
            Text('无法加载原文')
              .fontSize(17)
              .fontWeight(FontWeight.Bold)
              .fontColor('#B91C1C')
            Text(this.errorText)
              .fontSize(14)
              .lineHeight(22)
              .fontColor('#6B7280')
              .margin({ top: 10 })
              .textAlign(TextAlign.Center)
          }
          .width('100%')
          .padding(24)
          .margin({ top: 60 })
          .backgroundColor('#FFFFFF')
          .borderRadius(12)
        } else {
          Scroll() {
            Column() {
              Text(this.metaText)
                .fontSize(13)
                .fontColor('#6B7280')
                .width('100%')
              Text(this.title)
                .fontSize(22)
                .fontWeight(FontWeight.Bold)
                .fontColor('#1F2937')
                .lineHeight(32)
                .margin({ top: 8 })
                .width('100%')

              if (this.summaryText.length > 0) {
                Column() {
                  Text('AI 概括')
                    .fontSize(12)
                    .fontColor('#6B7280')
                  Text(this.summaryText)
                    .fontSize(15)
                    .lineHeight(24)
                    .fontColor('#1F2937')
                    .margin({ top: 6 })
                    .width('100%')
                }
                .alignItems(HorizontalAlign.Start)
                .width('100%')
                .padding(14)
                .margin({ top: 14 })
                .backgroundColor('#FFFFFF')
                .borderRadius(12)
              }

              if (this.annotations.length > 0) {
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
                .width('100%')
                .margin({ top: 6, bottom: 4 })
              }

              if (this.tipVisible) {
                Column() {
                  Row() {
                    Text(this.tipLabel)
                      .fontSize(12)
                      .fontColor('#374151')
                      .backgroundColor('#E5E7EB')
                      .borderRadius(6)
                      .padding({ left: 8, right: 8, top: 2, bottom: 2 })
                    Blank()
                    Text('收起')
                      .fontSize(12)
                      .fontColor('#6B7280')
                      .onClick(() => {
                        this.tipVisible = false;
                      })
                  }
                  .width('100%')
                  Text(this.tipText)
                    .fontSize(14)
                    .lineHeight(22)
                    .fontColor('#1F2937')
                    .margin({ top: 8 })
                    .width('100%')
                }
                .alignItems(HorizontalAlign.Start)
                .width('100%')
                .padding(12)
                .margin({ top: 8 })
                .backgroundColor('#FFFBEB')
                .borderRadius(10)
              }

              ForEach(this.paragraphs, (paragraph: string, index: number) => {
                this.paragraphBlock(index)
              }, (paragraph: string, index: number) => `${index}-${paragraph.length}`)
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
            .padding({ left: 16, right: 16, top: 12, bottom: 32 })
          }
          .width('100%')
          .layoutWeight(1)
          .align(Alignment.Top)
          .scrollBar(BarState.Off)
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor('#F5F1E8')
    }
    .title('阅读')
    .backgroundColor('#F5F1E8')
  }
}

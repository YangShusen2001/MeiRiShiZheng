import { ContentManifest, DigestItem, DigestSection, TodaySummary } from '../model/Content';
import { ContentService } from '../service/ContentService';
import { HttpError, STATUS_LOCAL_FAILURE } from '../service/Http';
import { Net } from '../service/Net';
import { KColor, KFont, KLine, KRadius, KShadow, KSize, KSpace } from '../theme/Tokens';
import { ReadParam } from './ReadPage';
import { SettingsSheet } from './SettingsSheet';

/**
 * 首页：日期切换 + 今日速览 + 当日日报（分栏列表）。
 *
 * 交互补齐项：
 * 1. **日期切换**——清单带 7 个内容日，首版只显示最新一天，历史内容完全无法触达；
 * 2. **下拉刷新**——失败后原先只能点「重试」按钮；
 * 3. **骨架屏**——首版是居中转圈，阅读类 App 用骨架屏更少跳动；
 * 4. **按压反馈 + 触摸目标**——列表行整行可点、高度 ≥44vp；
 * 5. **离线感知**——区分「设备没联网」与「服务异常」，不再笼统报「网络异常」；
 * 6. **阅读设置入口**——字号与深色在首页即可调整（夜间不必先点进文章才能切深色）。
 *
 * 视觉全部取自 `theme/Tokens.ets`，本文件不含任何硬编码色值/字号/间距。
 * 数据来自 `manifest.json` + `{date}/summary.json` + `{date}/digest.json`。
 */
@Component
export struct HomePage {
  @Consume('navStack') navStack: NavPathStack;
  /** 订阅主题与字号，使令牌取值变化时本页重建（子组件需各自订阅）。 */
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;
  @State loading: boolean = true;
  @State refreshing: boolean = false;
  @State errorText: string = '';
  @State hintText: string = '';
  @State dates: string[] = [];
  @State selectedDate: string = '';
  @State summaryText: string = '';
  @State keywords: string[] = [];
  @State sections: DigestSection[] = [];
  @State settingsOpen: boolean = false;

  /** 骨架屏占位行。 */
  private skeletonRows: number[] = [0, 1, 2, 3, 4];
  /** 官方原文链接 → 本地文章 id；用于日报条目跳转。 */
  private urlToId: Map<string, string> = new Map<string, string>();
  /** 官方原文链接 → 来源名（如「南方网」）。 */
  private urlToSource: Map<string, string> = new Map<string, string>();
  /** 日期 → 该日全部文章 id（按清单顺序），用于算上一篇/下一篇。 */
  private dayIds: Map<string, string[]> = new Map<string, string[]>();

  aboutToAppear(): void {
    this.loadLatest();
  }

  // —— 按压反馈：轻量背景变化（不做缩放，避免长列表滚动时抖动）——
  @Styles
  rowNormal() {
    .backgroundColor(KColor.surface())
  }

  @Styles
  rowPressed() {
    .backgroundColor(KColor.surfaceAlt())
  }

  private loadLatest(): void {
    this.loading = true;
    this.errorText = '';
    this.hintText = '';
    ContentService.loadManifest()
      .then((manifest: ContentManifest) => {
        const latest: string | null = manifest.latestDate;
        if (latest === null || latest.length === 0) {
          this.loading = false;
          this.refreshing = false;
          this.errorText = '内容清单为空：线上还没有可展示的日报。';
          return;
        }
        this.indexManifest(manifest);
        this.dates = manifest.days.map((day) => day.date);
        this.selectedDate = latest;
        this.loadDay(latest);
      })
      .catch((err: Error) => {
        this.report(err, true);
      });
  }

  private indexManifest(manifest: ContentManifest): void {
    this.urlToId.clear();
    this.urlToSource.clear();
    this.dayIds.clear();
    for (const day of manifest.days) {
      const ids: string[] = [];
      for (const article of day.articles) {
        this.urlToId.set(article.url, article.id);
        this.urlToSource.set(article.url, article.source);
        ids.push(article.id);
      }
      this.dayIds.set(day.date, ids);
    }
  }

  private loadDay(date: string): void {
    this.summaryText = '';
    this.keywords = [];
    this.sections = [];
    this.hintText = '';
    ContentService.loadSummary(date)
      .then((summary: TodaySummary) => {
        this.summaryText = summary.summary;
        this.keywords = summary.keywords;
      })
      .catch(() => {
        // 今日速览是可选产物：缺失不影响日报展示，不报错。
      })
      .then(() => ContentService.loadDigest(date))
      .then((digest) => {
        this.sections = digest.sections;
        this.loading = false;
        this.refreshing = false;
      })
      .catch((err: Error) => {
        this.report(err, true);
      });
  }

  private selectDate(date: string): void {
    if (date === this.selectedDate) {
      return;
    }
    this.selectedDate = date;
    this.loading = true;
    this.errorText = '';
    this.loadDay(date);
  }

  /**
   * 统一错误出口：先探测网络可达性，再决定提示措辞。
   * 报错时不武断归因——「没联网」和「服务异常」的处置动作完全不同。
   */
  private report(err: Error, stopLoading: boolean): void {
    Net.isOnline().then((online: boolean) => {
      this.errorText = HomePage.describe(err, online);
      if (stopLoading) {
        this.loading = false;
        this.refreshing = false;
      }
    });
  }

  private static describe(err: Error, online: boolean): string {
    if (err instanceof HttpError) {
      if (err.status === STATUS_LOCAL_FAILURE) {
        return err.message;
      }
      if (err.status === 404) {
        return '内容通道尚未部署到线上（/content/* 返回 404）。请先部署一次 Pages 构建。';
      }
      return `请求失败：HTTP ${err.status}`;
    }
    if (!online) {
      return '当前设备没有网络连接。请检查网络后下拉刷新。';
    }
    return `网络异常：${err.message}`;
  }

  private sourceOf(item: DigestItem): string {
    const name: string | undefined = this.urlToSource.get(item.sourceUrl);
    if (name !== undefined && name.length > 0) {
      return name;
    }
    return HomePage.hostOf(item.sourceUrl);
  }

  private static hostOf(url: string): string {
    const schemeAt: number = url.indexOf('://');
    const rest: string = schemeAt < 0 ? url : url.substring(schemeAt + 3);
    const slashAt: number = rest.indexOf('/');
    return slashAt < 0 ? rest : rest.substring(0, slashAt);
  }

  private summaryOf(item: DigestItem): string {
    const value: string | undefined = item.summary;
    return value === undefined ? '' : value;
  }

  private openItem(item: DigestItem): void {
    const articleId: string | undefined = this.urlToId.get(item.sourceUrl);
    if (articleId === undefined) {
      // 未剪藏的条目没有本地原文：给出明确提示，不静默失败也不跳外部浏览器。
      this.hintText = `「${item.title}」未收录原文，无法在本应用内阅读。`;
      return;
    }
    this.hintText = '';
    this.navStack.pushPathByName('read', this.readParamFor(articleId));
  }

  /** 带上当日文章列表：阅读页据此自行算出上一篇/下一篇，支持一直往下翻。 */
  private readParamFor(articleId: string): ReadParam {
    const ids: string[] | undefined = this.dayIds.get(this.selectedDate);
    const dayIds: string[] = ids === undefined ? [] : ids;
    const param: ReadParam = { articleId: articleId, dayIds: dayIds };
    return param;
  }

  /** 顶部：日期切换条 + 阅读设置入口。 */
  @Builder
  headerRow() {
    Row() {
      Scroll() {
        Row() {
          ForEach(this.dates, (date: string) => {
            Text(date.substring(5))
              .fontSize(KFont.meta())
              .fontColor(date === this.selectedDate ? KColor.surface() : KColor.sub())
              .backgroundColor(date === this.selectedDate ? KColor.primary() : KColor.surface())
              .borderRadius(KRadius.FULL)
              .height(KSize.TOUCH_MIN)
              .padding({ left: KSpace.L, right: KSpace.L })
              .margin({ right: KSpace.S })
              .textAlign(TextAlign.Center)
              .onClick(() => {
                this.selectDate(date);
              })
          }, (date: string) => date)
        }
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .layoutWeight(1)

      Text('Aa')
        .fontSize(KFont.meta())
        .fontColor(KColor.sub())
        .height(KSize.TOUCH_MIN)
        .padding({ left: KSpace.M, right: KSpace.XS })
        .textAlign(TextAlign.Center)
        .onClick(() => {
          this.settingsOpen = true;
        })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .margin({ bottom: KSpace.M })
  }

  /** 首屏骨架：结构与真实卡片一致，减少内容到达时的跳动。 */
  @Builder
  skeletonCard() {
    Column() {
      Row()
        .width(64)
        .height(KFont.titleM())
        .borderRadius(KRadius.XS)
        .backgroundColor(KColor.skeleton())

      ForEach(this.skeletonRows, () => {
        Column() {
          Row()
            .width('100%')
            .height(KFont.meta())
            .borderRadius(KRadius.XS)
            .backgroundColor(KColor.skeleton())
            .margin({ bottom: KSpace.S })
          Row()
            .width('62%')
            .height(KFont.meta())
            .borderRadius(KRadius.XS)
            .backgroundColor(KColor.skeleton())
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding({ top: KSpace.M, bottom: KSpace.M })
      }, (index: number) => `sk-${index}`)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(KSpace.L)
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
    .shadow({ radius: KShadow.CARD_RADIUS, color: KShadow.CARD_COLOR, offsetY: KShadow.CARD_OFFSET_Y })
  }

  @Builder
  summaryCard() {
    Column() {
      Text('今日速览')
        .fontSize(KFont.caption())
        .fontColor(KColor.sub())
      Text(this.summaryText)
        .fontSize(KFont.body())
        .lineHeight(KLine.normal())
        .fontColor(KColor.ink())
        .margin({ top: KSpace.S })
        .width('100%')
      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(this.keywords, (keyword: string) => {
          Text(keyword)
            .fontSize(KFont.caption())
            .fontColor(KColor.primaryText())
            .backgroundColor(KColor.primarySoft())
            .borderRadius(KRadius.FULL)
            .padding({ left: KSpace.M, right: KSpace.M, top: KSpace.XS, bottom: KSpace.XS })
            .margin({ right: KSpace.S, top: KSpace.S })
        }, (keyword: string) => keyword)
      }
      .margin({ top: KSpace.XS })
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(KSpace.L)
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
  }

  @Builder
  sectionBlock(section: DigestSection) {
    Column() {
      Row() {
        Text(section.title)
          .fontSize(KFont.titleS())
          .fontWeight(FontWeight.Bold)
          .fontColor(KColor.ink())
        Text(`${section.items.length} 条`)
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .margin({ left: KSpace.S })
      }
      .width('100%')
      .padding({ bottom: KSpace.XS })

      ForEach(section.items, (item: DigestItem, index: number) => {
        Row() {
          Text(`${index + 1}`)
            .fontSize(KFont.caption())
            .fontColor(KColor.mut())
            .width(KSpace.XXL)
          Column() {
            Text(item.title)
              .fontSize(KFont.body())
              .fontWeight(FontWeight.Medium)
              .fontColor(KColor.ink())
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .width('100%')
            if (this.summaryOf(item).length > 0) {
              Text(this.summaryOf(item))
                .fontSize(KFont.meta())
                .lineHeight(KLine.tight())
                .fontColor(KColor.sub())
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .margin({ top: KSpace.XS })
                .width('100%')
            }
            Text(this.sourceOf(item))
              .fontSize(KFont.caption())
              .fontColor(KColor.mut())
              .margin({ top: KSpace.S })
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .constraintSize({ minHeight: KSize.TOUCH_MIN })
        .padding({ top: KSpace.M, bottom: KSpace.M })
        .stateStyles({ normal: this.rowNormal, pressed: this.rowPressed })
        .onClick(() => {
          this.openItem(item);
        })
      }, (item: DigestItem, index: number) => `${index}-${item.sourceUrl}`)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(KSpace.L)
    .margin({ top: KSpace.M })
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
  }

  @Builder
  errorCard() {
    Column() {
      Text('无法加载内容')
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
          this.loadLatest();
        })
    }
    .width('100%')
    .padding(KSpace.XXL)
    .margin({ top: KSpace.XXXL })
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
  }

  @Builder
  content() {
    Column() {
      if (this.loading) {
        this.skeletonCard()
      } else if (this.errorText.length > 0) {
        this.errorCard()
      } else {
        if (this.summaryText.length > 0) {
          this.summaryCard()
        }
        if (this.hintText.length > 0) {
          Text(this.hintText)
            .fontSize(KFont.meta())
            .fontColor(KColor.warnInk())
            .backgroundColor(KColor.warnSoft())
            .borderRadius(KRadius.S)
            .padding(KSpace.M)
            .width('100%')
            .margin({ top: KSpace.M })
        }
        ForEach(this.sections, (section: DigestSection) => {
          this.sectionBlock(section)
        }, (section: DigestSection) => `${this.selectedDate}-${section.id}`)
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    Stack({ alignContent: Alignment.Bottom }) {
      Refresh({ refreshing: $$this.refreshing }) {
        Scroll() {
          Column() {
            this.headerRow()
            this.content()
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .padding({ left: KSpace.PAGE, right: KSpace.PAGE, top: KSpace.M, bottom: KSpace.XXL })
        }
        .width('100%')
        .height('100%')
        .align(Alignment.Top)
        .scrollBar(BarState.Off)
      }
      .onRefreshing(() => {
        this.loadLatest();
      })
      .width('100%')
      .height('100%')
      .backgroundColor(KColor.bg())

      if (this.settingsOpen) {
        Column()
          .width('100%')
          .height('100%')
          .backgroundColor(KColor.scrim())
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
}

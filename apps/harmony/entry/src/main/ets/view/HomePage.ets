import { ContentManifest, DigestItem, DigestSection, TodaySummary } from '../model/Content';
import { ContentService } from '../service/ContentService';
import { HttpError, STATUS_LOCAL_FAILURE } from '../service/Http';
import { KColor, KFont, KLine, KRadius, KShadow, KSpace } from '../theme/Tokens';
import { ReadParam } from './ReadPage';

/**
 * 首页：日期切换 + 今日速览 + 当日日报（分栏列表）。
 *
 * 交互补齐项（相对首版）：
 * 1. **日期切换**——清单本身带 7 个内容日，首版只显示最新一天，历史内容完全无法触达；
 * 2. **下拉刷新**——失败后原先只能点「重试」按钮；
 * 3. **骨架屏**——首版是居中转圈，阅读类 App 用骨架屏更少跳动；
 * 4. **按压反馈 + 触摸目标**——列表行整行可点、高度 ≥44vp（可达性下限）。
 *
 * 视觉全部取自 `theme/Tokens.ets`，本文件不含任何硬编码色值/字号/间距。
 * 数据来自 `manifest.json` + `{date}/summary.json` + `{date}/digest.json`。
 */
@Component
export struct HomePage {
  @Consume('navStack') navStack: NavPathStack;
  @State loading: boolean = true;
  @State refreshing: boolean = false;
  @State errorText: string = '';
  @State hintText: string = '';
  @State dates: string[] = [];
  @State selectedDate: string = '';
  @State summaryText: string = '';
  @State keywords: string[] = [];
  @State sections: DigestSection[] = [];

  /** 骨架屏占位行。 */
  private skeletonRows: number[] = [0, 1, 2, 3, 4];
  /** 官方原文链接 → 本地文章 id；用于日报条目跳转。 */
  private urlToId: Map<string, string> = new Map<string, string>();
  /** 官方原文链接 → 来源名（如「南方网」）。 */
  private urlToSource: Map<string, string> = new Map<string, string>();

  aboutToAppear(): void {
    this.loadLatest();
  }

  // —— 按压反馈：轻量背景变化（不做缩放，避免长列表滚动时抖动）——
  @Styles
  rowNormal() {
    .backgroundColor(KColor.SURFACE)
  }

  @Styles
  rowPressed() {
    .backgroundColor(KColor.SURFACE_ALT)
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
        this.loading = false;
        this.refreshing = false;
        this.errorText = HomePage.describe(err);
      });
  }

  private indexManifest(manifest: ContentManifest): void {
    this.urlToId.clear();
    this.urlToSource.clear();
    for (const day of manifest.days) {
      for (const article of day.articles) {
        this.urlToId.set(article.url, article.id);
        this.urlToSource.set(article.url, article.source);
      }
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
        this.errorText = HomePage.describe(err);
        this.loading = false;
        this.refreshing = false;
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

  private static describe(err: Error): string {
    if (err instanceof HttpError) {
      if (err.status === STATUS_LOCAL_FAILURE) {
        return err.message;
      }
      if (err.status === 404) {
        return '内容通道尚未部署到线上（/content/* 返回 404）。请先部署一次 Pages 构建。';
      }
      return `请求失败：HTTP ${err.status}`;
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
    const param: ReadParam = { articleId: articleId };
    this.navStack.pushPathByName('read', param);
  }

  /** 日期切换条：横向可滚，选中态用品牌色填充。 */
  @Builder
  dateStrip() {
    Scroll() {
      Row() {
        ForEach(this.dates, (date: string) => {
          Text(date.substring(5))
            .fontSize(KFont.META)
            .fontColor(date === this.selectedDate ? KColor.SURFACE : KColor.SUB)
            .backgroundColor(date === this.selectedDate ? KColor.PRIMARY : KColor.SURFACE)
            .borderRadius(KRadius.FULL)
            .height(44)
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
    .width('100%')
    .margin({ bottom: KSpace.M })
  }

  /** 首屏骨架：结构与真实卡片一致，减少内容到达时的跳动。 */
  @Builder
  skeletonCard() {
    Column() {
      Row()
        .width(64)
        .height(KFont.TITLE_M)
        .borderRadius(KRadius.XS)
        .backgroundColor(KColor.SKELETON)

      ForEach(this.skeletonRows, () => {
        Column() {
          Row()
            .width('100%')
            .height(KFont.META)
            .borderRadius(KRadius.XS)
            .backgroundColor(KColor.SKELETON)
            .margin({ bottom: KSpace.S })
          Row()
            .width('62%')
            .height(KFont.META)
            .borderRadius(KRadius.XS)
            .backgroundColor(KColor.SKELETON)
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
        .padding({ top: KSpace.M, bottom: KSpace.M })
      }, (index: number) => `sk-${index}`)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(KSpace.L)
    .backgroundColor(KColor.SURFACE)
    .borderRadius(KRadius.L)
    .shadow({ radius: KShadow.CARD_RADIUS, color: KShadow.CARD_COLOR, offsetY: KShadow.CARD_OFFSET_Y })
  }

  @Builder
  summaryCard() {
    Column() {
      Text('今日速览')
        .fontSize(KFont.CAPTION)
        .fontColor(KColor.SUB)
      Text(this.summaryText)
        .fontSize(KFont.BODY)
        .lineHeight(KLine.NORMAL)
        .fontColor(KColor.INK)
        .margin({ top: KSpace.S })
        .width('100%')
      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(this.keywords, (keyword: string) => {
          Text(keyword)
            .fontSize(KFont.CAPTION)
            .fontColor(KColor.PRIMARY_TEXT)
            .backgroundColor(KColor.PRIMARY_SOFT)
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
    .backgroundColor(KColor.SURFACE)
    .borderRadius(KRadius.L)
  }

  @Builder
  sectionBlock(section: DigestSection) {
    Column() {
      Row() {
        Text(section.title)
          .fontSize(KFont.TITLE_S)
          .fontWeight(FontWeight.Bold)
          .fontColor(KColor.INK)
        Text(`${section.items.length} 条`)
          .fontSize(KFont.CAPTION)
          .fontColor(KColor.MUT)
          .margin({ left: KSpace.S })
      }
      .width('100%')
      .padding({ bottom: KSpace.XS })

      ForEach(section.items, (item: DigestItem, index: number) => {
        Row() {
          Text(`${index + 1}`)
            .fontSize(KFont.CAPTION)
            .fontColor(KColor.MUT)
            .width(KSpace.XXL)
          Column() {
            Text(item.title)
              .fontSize(KFont.BODY)
              .fontWeight(FontWeight.Medium)
              .fontColor(KColor.INK)
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .width('100%')
            if (this.summaryOf(item).length > 0) {
              Text(this.summaryOf(item))
                .fontSize(KFont.META)
                .lineHeight(KLine.TIGHT)
                .fontColor(KColor.SUB)
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .margin({ top: KSpace.XS })
                .width('100%')
            }
            Text(this.sourceOf(item))
              .fontSize(KFont.CAPTION)
              .fontColor(KColor.MUT)
              .margin({ top: KSpace.S })
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .constraintSize({ minHeight: 44 })
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
    .backgroundColor(KColor.SURFACE)
    .borderRadius(KRadius.L)
  }

  @Builder
  errorCard() {
    Column() {
      Text('无法加载内容')
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
          this.loadLatest();
        })
    }
    .width('100%')
    .padding(KSpace.XXL)
    .margin({ top: KSpace.XXXL })
    .backgroundColor(KColor.SURFACE)
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
            .fontSize(KFont.META)
            .fontColor(KColor.WARN_INK)
            .backgroundColor(KColor.WARN_SOFT)
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
    Refresh({ refreshing: $$this.refreshing }) {
      Scroll() {
        Column() {
          this.dateStrip()
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
    .backgroundColor(KColor.BG)
  }
}

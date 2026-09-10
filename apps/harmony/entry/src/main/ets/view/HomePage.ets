import { ContentManifest, DigestItem, DigestSection, TodaySummary } from '../model/Content';
import { ContentService } from '../service/ContentService';
import { HttpError, STATUS_LOCAL_FAILURE } from '../service/Http';
import { ReadParam } from './ReadPage';

/**
 * 首页：今日速览 + 当日日报（分栏列表）。
 *
 * 数据只来自 `manifest.json` + `{date}/summary.json` + `{date}/digest.json`：
 * 清单里已带每篇文章的 id/title/source/url，所以「日报条目 sourceUrl → 文章 id」
 * 可在本地完成反查，无需逐篇拉取全文（与 Web 端 clipMap 同源逻辑）。
 */
@Component
export struct HomePage {
  @Consume('navStack') navStack: NavPathStack;
  @State loading: boolean = true;
  @State errorText: string = '';
  @State hintText: string = '';
  @State dateText: string = '';
  @State summaryText: string = '';
  @State keywords: string[] = [];
  @State sections: DigestSection[] = [];

  /** 官方原文链接 → 本地文章 id；用于日报条目跳转。 */
  private urlToId: Map<string, string> = new Map<string, string>();
  /** 官方原文链接 → 来源名（如「南方网」）。 */
  private urlToSource: Map<string, string> = new Map<string, string>();

  aboutToAppear(): void {
    this.loadLatest();
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
          this.errorText = '内容清单为空：线上还没有可展示的日报。';
          return;
        }
        this.indexManifest(manifest);
        this.dateText = latest;
        this.loadDay(latest);
      })
      .catch((err: Error) => {
        this.loading = false;
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
      })
      .catch((err: Error) => {
        this.errorText = HomePage.describe(err);
        this.loading = false;
      });
  }

  private static describe(err: Error): string {
    if (err instanceof HttpError) {
      if (err.status === STATUS_LOCAL_FAILURE) {
        // 已是可执行提示（响应不是 JSON）
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
      // 未剪藏的条目没有本地原文：明确提示，不静默失败也不跳外部浏览器。
      this.hintText = `「${item.title}」未收录原文，无法在本应用内阅读。`;
      return;
    }
    this.hintText = '';
    const param: ReadParam = { articleId: articleId };
    this.navStack.pushPathByName('read', param);
  }

  @Builder
  summaryCard() {
    Column() {
      Text('今日速览')
        .fontSize(13)
        .fontColor('#6B7280')
      Text(this.summaryText)
        .fontSize(16)
        .lineHeight(26)
        .fontColor('#1F2937')
        .margin({ top: 8 })
        .width('100%')
      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(this.keywords, (keyword: string) => {
          Text(keyword)
            .fontSize(12)
            .fontColor('#4C795B')
            .backgroundColor('#E6EFE8')
            .borderRadius(10)
            .padding({ left: 10, right: 10, top: 4, bottom: 4 })
            .margin({ right: 8, top: 10 })
        })
      }
      .margin({ top: 4 })
      .width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .borderRadius(12)
  }

  @Builder
  sectionBlock(section: DigestSection) {
    Column() {
      Row() {
        Text(section.title)
          .fontSize(17)
          .fontWeight(FontWeight.Bold)
          .fontColor('#1F2937')
        Text(`${section.items.length} 条`)
          .fontSize(12)
          .fontColor('#9CA3AF')
          .margin({ left: 8 })
      }
      .width('100%')
      .padding({ bottom: 4 })

      ForEach(section.items, (item: DigestItem, index: number) => {
        Row() {
          Text(`${index + 1}`)
            .fontSize(12)
            .fontColor('#6B7280')
            .width(22)
            .textAlign(TextAlign.Center)
          Column() {
            Text(item.title)
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor('#1F2937')
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .width('100%')
            if (this.summaryOf(item).length > 0) {
              Text(this.summaryOf(item))
                .fontSize(13)
                .lineHeight(21)
                .fontColor('#6B7280')
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .margin({ top: 4 })
                .width('100%')
            }
            Text(this.sourceOf(item))
              .fontSize(12)
              .fontColor('#9CA3AF')
              .margin({ top: 6 })
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)
        .padding({ top: 12, bottom: 12 })
        .onClick(() => {
          this.openItem(item);
        })
      }, (item: DigestItem, index: number) => `${index}-${item.sourceUrl}`)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(16)
    .margin({ top: 12 })
    .backgroundColor('#FFFFFF')
    .borderRadius(12)
  }

  build() {
    Scroll() {
      Column() {
        if (this.loading) {
          Row() {
            LoadingProgress().width(28).height(28)
            Text('正在读取云端内容…').fontSize(14).fontColor('#6B7280').margin({ left: 10 })
          }
          .margin({ top: 80 })
        } else if (this.errorText.length > 0) {
          Column() {
            Text('无法加载内容')
              .fontSize(17)
              .fontWeight(FontWeight.Bold)
              .fontColor('#B91C1C')
            Text(this.errorText)
              .fontSize(14)
              .lineHeight(22)
              .fontColor('#6B7280')
              .margin({ top: 10 })
              .textAlign(TextAlign.Center)
            Button('重试')
              .margin({ top: 18 })
              .onClick(() => {
                this.loadLatest();
              })
          }
          .width('100%')
          .padding(24)
          .margin({ top: 60 })
          .backgroundColor('#FFFFFF')
          .borderRadius(12)
        } else {
          Text(this.dateText)
            .fontSize(13)
            .fontColor('#6B7280')
            .width('100%')
            .margin({ bottom: 10 })
          if (this.summaryText.length > 0) {
            this.summaryCard()
          }
          if (this.hintText.length > 0) {
            Text(this.hintText)
              .fontSize(13)
              .fontColor('#92400E')
              .backgroundColor('#FEF3C7')
              .borderRadius(8)
              .padding(10)
              .width('100%')
              .margin({ top: 12 })
          }
          ForEach(this.sections, (section: DigestSection) => {
            this.sectionBlock(section)
          }, (section: DigestSection) => section.id)
        }
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 12, bottom: 24 })
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .height('100%')
    .align(Alignment.Top)
    .scrollBar(BarState.Off)
    .backgroundColor('#F5F1E8')
  }
}

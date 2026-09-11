import { ContentManifest, DailyDigest, DigestItem, DigestSection, TodaySummary } from '../model/Content';
import { ContentService, Loaded } from '../service/ContentService';
import { HttpError, STATUS_LOCAL_FAILURE } from '../service/Http';
import { Net } from '../service/Net';
import { KColor, KFont, KLine, KRadius, KShadow, KSize, KSpace } from '../theme/Tokens';
import { ReadParam } from './ReadPage';
import { SearchHit, SearchSheet } from './SearchSheet';
import { SettingsSheet } from './SettingsSheet';

/**
 * 首页：日期切换 + 今日速览 + 当日日报（分栏列表）。
 *
 * ## 数据与离线
 * 取数一律走 `ContentService`（内部先网络、失败回落缓存）。
 * **冷启动先同步读缓存渲染首帧**（`paintFromCache`），再后台请求刷新——
 * 这是"秒开"的关键：异步读缓存会先闪一帧空白。首帧来自缓存时明确标注，
 * 不让用户误以为内容是最新的。
 *
 * ## 交互
 * 日期切换 · 下拉刷新 · 骨架屏 · 按压反馈 · 断网/缓存状态条 ·
 * **跨日检索**（本地索引，零网络）· 阅读设置入口 · 空态
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
  @State searchOpen: boolean = false;
  /** 设备当前是否断网。由 `Net.watch` 持续更新。 */
  @State offline: boolean = false;
  /** 当前展示内容是否来自缓存（含首帧秒开与断网兜底两种）。 */
  @State showingCache: boolean = false;
  /** 缓存写入时间，用于「缓存于 x 前」。 */
  @State cachedAt: number = 0;

  /** 骨架屏占位行。 */
  private skeletonRows: number[] = [0, 1, 2, 3, 4];
  /** 官方原文链接 → 本地文章 id。 */
  private urlToId: Map<string, string> = new Map<string, string>();
  /** 官方原文链接 → 来源名。 */
  private urlToSource: Map<string, string> = new Map<string, string>();
  /** 日期 → 该日全部文章 id（按清单顺序），用于算上一篇/下一篇。 */
  private dayIds: Map<string, string[]> = new Map<string, string[]>();
  /** 检索索引（全量文章）。非状态字段：仅在 manifest 更新时重建。 */
  private searchHits: SearchHit[] = [];

  aboutToAppear(): void {
    Net.watch((online: boolean) => {
      this.offline = !online;
      if (online) {
        this.loadLatest();
      }
    });
    Net.probe().then((online: boolean) => {
      this.offline = !online;
    });
    // 先拿缓存把首帧点亮，再走网络刷新
    this.paintFromCache();
    this.loadLatest();
  }

  aboutToDisappear(): void {
    Net.unwatch();
  }

  @Styles
  rowNormal() {
    .backgroundColor(KColor.surface())
  }

  @Styles
  rowPressed() {
    .backgroundColor(KColor.surfaceAlt())
  }

  /**
   * 用缓存渲染首帧。返回 true 表示已有内容可展示（此时不显示骨架屏）。
   * 必须同步读：异步读会让用户先看到一帧空白，秒开就失去意义。
   */
  private paintFromCache(): boolean {
    const manifest: Loaded<ContentManifest> | null = ContentService.cachedManifest();
    if (manifest === null) {
      return false;
    }
    const latest: string | null = manifest.data.latestDate;
    if (latest === null || latest.length === 0) {
      return false;
    }
    this.applyManifest(manifest.data);
    this.selectedDate = latest;
    const digest: Loaded<DailyDigest> | null = ContentService.cachedDigest(latest);
    if (digest !== null) {
      this.sections = digest.data.sections;
    }
    const summary: Loaded<TodaySummary> | null = ContentService.cachedSummary(latest);
    if (summary !== null) {
      this.summaryText = summary.data.summary;
      this.keywords = summary.data.keywords;
    }
    this.showingCache = true;
    this.cachedAt = manifest.savedAt;
    this.loading = this.sections.length === 0;
    return this.sections.length > 0;
  }

  /** 重建各层索引（manifest 是全量索引的唯一来源）。 */
  private applyManifest(manifest: ContentManifest): void {
    this.urlToId.clear();
    this.urlToSource.clear();
    this.dayIds.clear();
    const hits: SearchHit[] = [];
    for (const day of manifest.days) {
      const ids: string[] = [];
      for (const article of day.articles) {
        this.urlToId.set(article.url, article.id);
        this.urlToSource.set(article.url, article.source);
        ids.push(article.id);
        hits.push({ id: article.id, title: article.title, source: article.source, date: day.date });
      }
      this.dayIds.set(day.date, ids);
    }
    this.searchHits = hits;
    this.dates = manifest.days.map((day) => day.date);
  }

  private loadLatest(): void {
    if (!this.showingCache) {
      this.loading = true;
    }
    this.errorText = '';
    this.hintText = '';
    ContentService.loadManifest()
      .then((loaded: Loaded<ContentManifest>) => {
        const latest: string | null = loaded.data.latestDate;
        if (latest === null || latest.length === 0) {
          this.loading = false;
          this.refreshing = false;
          this.errorText = '内容清单为空：线上还没有可展示的日报。';
          return;
        }
        this.applyManifest(loaded.data);
        this.selectedDate = latest;
        this.showingCache = loaded.cached;
        this.cachedAt = loaded.savedAt;
        this.loadDay(latest);
      })
      .catch((err: Error) => {
        this.report(err, true);
      });
  }

  private loadDay(date: string): void {
    this.hintText = '';
    ContentService.loadSummary(date)
      .then((loaded: Loaded<TodaySummary>) => {
        this.summaryText = loaded.data.summary;
        this.keywords = loaded.data.keywords;
      })
      .catch(() => {
        // 今日速览是可选产物：缺失不影响日报展示，不报错。
      })
      .then(() => ContentService.loadDigest(date))
      .then((loaded: Loaded<DailyDigest>) => {
        this.sections = loaded.data.sections;
        this.showingCache = loaded.cached;
        this.cachedAt = loaded.savedAt;
        this.errorText = '';
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
    this.errorText = '';
    // 切日期时先用该日缓存立刻给内容，再刷新
    const cached: Loaded<DailyDigest> | null = ContentService.cachedDigest(date);
    if (cached !== null) {
      this.sections = cached.data.sections;
      this.showingCache = true;
      this.cachedAt = cached.savedAt;
      this.loading = false;
    } else {
      this.sections = [];
      this.summaryText = '';
      this.keywords = [];
      this.loading = true;
    }
    this.loadDay(date);
  }

  private report(err: Error, stopLoading: boolean): void {
    Net.probe().then((online: boolean) => {
      this.offline = !online;
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
        return '内容通道尚未部署到线上（/content/* 返回 404）。';
      }
      return `请求失败：HTTP ${err.status}`;
    }
    if (!online) {
      return '当前无网络，且本地还没有缓存内容。联网后下拉刷新即可。';
    }
    return `网络异常：${err.message}`;
  }

  /** 「缓存于 x 前」。 */
  private static agoText(savedAt: number): string {
    if (savedAt <= 0) {
      return '';
    }
    const minutes: number = Math.floor((Date.now() - savedAt) / 60000);
    if (minutes < 1) {
      return '刚刚';
    }
    if (minutes < 60) {
      return `${minutes} 分钟前`;
    }
    const hours: number = Math.floor(minutes / 60);
    if (hours < 24) {
      return `${hours} 小时前`;
    }
    return `${Math.floor(hours / 24)} 天前`;
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
      this.hintText = `「${item.title}」未收录原文，无法在本应用内阅读。`;
      return;
    }
    this.hintText = '';
    this.navStack.pushPathByName('read', this.readParamFor(articleId, this.selectedDate));
  }

  /** 检索命中 → 打开文章（带上该文章所属日期的清单，保证篇间翻阅可用）。 */
  private openHit(hit: SearchHit): void {
    this.searchOpen = false;
    if (hit.date !== this.selectedDate) {
      this.selectDate(hit.date);
    }
    this.navStack.pushPathByName('read', this.readParamFor(hit.id, hit.date));
  }

  private readParamFor(articleId: string, date: string): ReadParam {
    const ids: string[] | undefined = this.dayIds.get(date);
    const dayIds: string[] = ids === undefined ? [] : ids;
    const param: ReadParam = { articleId: articleId, dayIds: dayIds };
    return param;
  }

  /** 顶部：日期切换条 + 检索 / 设置入口。 */
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

      Text('检索')
        .fontSize(KFont.meta())
        .fontColor(KColor.sub())
        .height(KSize.TOUCH_MIN)
        .padding({ left: KSpace.S, right: KSpace.S })
        .textAlign(TextAlign.Center)
        .onClick(() => {
          this.searchOpen = true;
        })

      Text('Aa')
        .fontSize(KFont.meta())
        .fontColor(KColor.sub())
        .height(KSize.TOUCH_MIN)
        .padding({ left: KSpace.XS, right: KSpace.XS })
        .textAlign(TextAlign.Center)
        .onClick(() => {
          this.settingsOpen = true;
        })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .margin({ bottom: KSpace.M })
  }

  /** 离线 / 缓存状态条：如实告知内容来源，不冒充"刚刚更新"。 */
  @Builder
  statusStrip() {
    if (this.offline) {
      Text(this.showingCache
        ? `当前无网络，展示的是缓存内容（${HomePage.agoText(this.cachedAt)}）。恢复后会自动刷新。`
        : '当前无网络，且本地没有缓存内容。联网后下拉刷新即可。')
        .fontSize(KFont.meta())
        .lineHeight(KLine.tight())
        .fontColor(KColor.warnInk())
        .backgroundColor(KColor.warnSoft())
        .borderRadius(KRadius.S)
        .padding(KSpace.M)
        .width('100%')
        .margin({ bottom: KSpace.M })
    } else if (this.showingCache) {
      Text(`离线内容（缓存于 ${HomePage.agoText(this.cachedAt)}），正在刷新…`)
        .fontSize(KFont.caption())
        .fontColor(KColor.mut())
        .width('100%')
        .margin({ bottom: KSpace.M })
    }
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

  /** 空态：该日没有内容。给出可执行的方向，不留白。 */
  @Builder
  emptyCard() {
    Column() {
      Text('这一天没有内容')
        .fontSize(KFont.titleS())
        .fontWeight(FontWeight.Bold)
        .fontColor(KColor.ink())
      Text('可能当天未产出日报。可切换其他日期，或用「检索」找往期文章。')
        .fontSize(KFont.meta())
        .lineHeight(KLine.tight())
        .fontColor(KColor.sub())
        .margin({ top: KSpace.S })
        .textAlign(TextAlign.Center)
    }
    .width('100%')
    .padding(KSpace.XXL)
    .margin({ top: KSpace.XXXL })
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
      this.statusStrip()

      if (this.loading) {
        this.skeletonCard()
      } else if (this.errorText.length > 0) {
        this.errorCard()
      } else if (this.sections.length === 0) {
        this.emptyCard()
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

      if (this.searchOpen) {
        Column()
          .width('100%')
          .height('100%')
          .backgroundColor(KColor.scrim())
          .transition(TransitionEffect.OPACITY)
          .onClick(() => {
            this.searchOpen = false;
          })
        SearchSheet({
          hits: this.searchHits,
          onPick: (hit: SearchHit) => {
            this.openHit(hit);
          },
          onClose: () => {
            this.searchOpen = false;
          },
        })
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(KColor.bg())
  }
}

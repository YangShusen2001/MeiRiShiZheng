import {
  ContentArchiveIndex,
  ContentArchiveItem,
  ContentArchiveMonth,
  ContentArchiveMonthRow,
} from '../model/Content';
import { Archive, ArchiveTier } from '../service/Archive';
import { Clipboard } from '../service/Clipboard';
import { ContentService, Loaded } from '../service/ContentService';
import { archiveTagBg, archiveTagInk, KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';
import { ReadParam } from './ReadPage';

/**
 * 政策档案页（中国政府网政策文件库 · 按月成台账）。
 *
 * ## 为什么要有这一页
 * Web 端的 `/policy/` 从 `content/archive/` 构建期读取；分发层原先**完全没有档案**，
 * 鸿蒙端物理上取不到 —— 三端在「政策档案」这一屏上是不通的。2026-09-15 补齐：
 * 分发层产出 `archive/index.json` + `archive/<YYYY-MM>.json`，
 * 档案正文与日更正文共用 `articles/<id>.json`（同一 id 空间）。
 *
 * ## 结构（对齐 Web 月份页，按手机宽度重排）
 * 页头（标题 + 全馆三项统计）→ 月份胶囊条（横向，跨年处插年份标）→
 * 本月台账（核心考点卡 → 了解 · 细则行）。
 *
 * ## 两处刻意的形态差异（不是漏做）
 * 1. Web 侧边栏是 240 定宽竖排；手机宽不够，改为横向月份条 —— 同样的「月份导航」语义；
 * 2. Web「导出本月清单」是前端拼 CSV；鸿蒙端没有"下载到文件"的通用落点，
 *    这一项**不做**（宁缺勿滥，不做一个点了没反应或存不进相册的导出）。
 *
 * ## 外链条目
 * `readId` 为空的条目没有站内正文，只能指官方原文。鸿蒙端不直接拉浏览器
 * （与阅读页同策）：**复制链接**并如实反馈，不让用户点了没反应。
 */
@Component
export struct ArchivePage {
  @Consume('navStack') navStack: NavPathStack;
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;

  @State loading: boolean = true;
  @State errorText: string = '';
  /** 索引来自缓存（离线或首帧秒开）—— 必须如实标注，否则用户以为看到的是最新台账。 */
  @State indexCached: boolean = false;

  @State months: ContentArchiveMonthRow[] = [];
  @State selectedMonth: string = '';
  /** 全馆统计拆成三个数：避免在 build 里访问可空对象（ArkTS 对 @State 的可空收窄不可靠）。 */
  @State totalMonths: number = 0;
  @State totalFiles: number = 0;
  @State totalCore: number = 0;
  @State firstMonth: string = '';

  @State monthLoading: boolean = false;
  @State monthError: string = '';
  @State monthCached: boolean = false;
  /** 本月台账拆成标题行 + 两组条目，同样是避开可空对象访问。 */
  @State monthTitle: string = '';
  @State monthSummary: string = '';
  @State coreItems: ContentArchiveItem[] = [];
  @State restItems: ContentArchiveItem[] = [];

  /** 展开的「了解 · 细则」行（按 url 记，一次只展开一条，避免长列表被撑散）。 */
  @State expandedUrl: string = '';
  /** 复制外链后的反馈文案。 */
  @State hintText: string = '';
  /** 当前正在拉取的月份：用于丢弃"快速连点切月"时的过期响应。 */
  private inflightMonth: string = '';

  aboutToAppear(): void {
    this.paintFromCache();
    this.loadIndex();
  }

  /** 冷启动先用缓存把首帧点亮（同步读，异步读会先闪一帧空白）。 */
  private paintFromCache(): void {
    const cachedIndex: Loaded<ContentArchiveIndex> | null = ContentService.cachedArchiveIndex();
    if (cachedIndex === null) {
      return;
    }
    this.applyIndex(cachedIndex.data, true);
    const first: string = this.selectedMonth;
    if (first.length === 0) {
      return;
    }
    const cachedMonth: Loaded<ContentArchiveMonth> | null = ContentService.cachedArchiveMonth(first);
    if (cachedMonth !== null) {
      this.applyMonth(cachedMonth.data, true);
      this.loading = false;
    }
  }

  private loadIndex(): void {
    this.errorText = '';
    ContentService.loadArchiveIndex()
      .then((loaded: Loaded<ContentArchiveIndex>) => {
        this.applyIndex(loaded.data, loaded.cached);
        if (this.selectedMonth.length > 0) {
          this.loadMonth(this.selectedMonth);
        } else {
          // 索引为空（档案还没上线）：如实进空态，不假装在加载
          this.loading = false;
        }
      })
      .catch((err: Error) => {
        this.errorText = err.message;
        this.loading = false;
      });
  }

  private applyIndex(index: ContentArchiveIndex, cached: boolean): void {
    this.months = index.months;
    this.totalMonths = index.totals.months;
    this.totalFiles = index.totals.files;
    this.totalCore = index.totals.core;
    this.firstMonth = index.totals.firstMonth;
    this.indexCached = cached;
    // 默认选最新月份；已选月份仍存在则保持不变（避免刷新后跳回第一月）
    if (this.selectedMonth.length === 0 || !this.hasMonth(this.selectedMonth)) {
      this.selectedMonth = this.months.length > 0 ? this.months[0].month : '';
    }
  }

  private hasMonth(month: string): boolean {
    return this.months.some((row: ContentArchiveMonthRow) => row.month === month);
  }

  private applyMonth(doc: ContentArchiveMonth, cached: boolean): void {
    this.monthTitle = Archive.monthLabel(doc.month);
    const rest: number = doc.count - doc.high;
    this.monthSummary = `共 ${doc.count} 份 · 核心考点 ${doc.high} 份 · 了解细则 ${rest} 份`;
    this.coreItems = Archive.coreOf(doc.items);
    this.restItems = Archive.restOf(doc.items);
    this.monthCached = cached;
    this.monthLoading = false;
    this.monthError = '';
  }

  private selectMonth(month: string): void {
    if (month === this.selectedMonth) {
      return;
    }
    this.selectedMonth = month;
    this.expandedUrl = '';
    this.hintText = '';
    // 有缓存先上屏（切月要立刻有反馈），再走网络刷新
    const cached: Loaded<ContentArchiveMonth> | null = ContentService.cachedArchiveMonth(month);
    if (cached !== null) {
      this.applyMonth(cached.data, true);
    } else {
      this.monthLoading = true;
      this.monthError = '';
      this.monthTitle = '';
      this.monthSummary = '';
      this.coreItems = [];
      this.restItems = [];
    }
    this.loadMonth(month);
  }

  private loadMonth(month: string): void {
    this.inflightMonth = month;
    ContentService.loadArchiveMonth(month)
      .then((loaded: Loaded<ContentArchiveMonth>) => {
        // 快速连点切月：过期响应必须丢弃，否则会把当前月份的内容盖掉
        if (this.inflightMonth !== month) {
          return;
        }
        this.applyMonth(loaded.data, loaded.cached);
      })
      .catch((err: Error) => {
        if (this.inflightMonth !== month) {
          return;
        }
        this.monthError = err.message;
        this.monthLoading = false;
      });
  }

  /**
   * 条目主操作。
   * 有正文 → 站内阅读页（与 Web 端同一套 `/read/<id>/` 正文）；
   * 无正文 → 复制官方链接（鸿蒙端不直接拉浏览器，与阅读页的「复制原文链接」同策）。
   */
  private openItem(item: ContentArchiveItem): void {
    if (item.readId.length > 0) {
      const param: ReadParam = { articleId: item.readId, dayIds: [] };
      this.navStack.pushPathByName('read', param);
      return;
    }
    Clipboard.copyText(item.url).then((ok: boolean) => {
      this.hintText = ok ? '官方链接已复制，可到浏览器打开' : '复制失败，请稍后重试';
      setTimeout(() => {
        this.hintText = '';
      }, 3000);
    });
  }

  private toggleRow(item: ContentArchiveItem): void {
    this.expandedUrl = this.expandedUrl === item.url ? '' : item.url;
  }

  /** 是否在月份条上这一项之前插年份标（首个，或跨年处）。 */
  private needYearMark(index: number): boolean {
    if (index === 0) {
      return true;
    }
    return Archive.yearOf(this.months[index].month) !== Archive.yearOf(this.months[index - 1].month);
  }

  // —— 视图 ——

  @Builder
  head() {
    Column() {
      Text('政策档案')
        .fontSize(KFont.titleL())
        .fontWeight(FontWeight.Bold)
        .fontColor(KColor.ink())
        .width('100%')
      Text('中国政府网政策文件库 · 国务院文件与部门文件 · 按月成台账，只留核心')
        .fontSize(KFont.caption())
        .lineHeight(KLine.tight())
        .fontColor(KColor.sub())
        .margin({ top: KSpace.XS })
        .width('100%')

      Row() {
        this.statCell(`${this.totalMonths}`, '个月', false)
        this.statCell(`${this.totalFiles}`, '政策文件', false)
        this.statCell(`${this.totalCore}`, '核心考点', true)
      }
      .width('100%')
      .margin({ top: KSpace.L })

      if (this.firstMonth.length > 0) {
        Text(`${this.firstMonth} 起 · 每月台账自动更新`)
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .margin({ top: KSpace.S })
          .width('100%')
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  statCell(value: string, label: string, brand: boolean) {
    Column() {
      Text(value)
        .fontSize(KFont.titleM())
        .fontWeight(FontWeight.Bold)
        .fontColor(brand ? KColor.primaryText() : KColor.ink())
      Text(label)
        .fontSize(KFont.caption())
        .fontColor(KColor.mut())
        .margin({ top: KSpace.HAIR })
    }
    .alignItems(HorizontalAlign.Start)
    .layoutWeight(1)
  }

  /** 月份条：横向滚动，跨年处插年份标。21 个月的台账竖排会把首屏全占掉。 */
  @Builder
  monthStrip() {
    Scroll() {
      Row() {
        ForEach(this.months, (row: ContentArchiveMonthRow, index: number) => {
          if (this.needYearMark(index)) {
            Text(Archive.yearOf(row.month))
              .fontSize(KFont.caption())
              .fontWeight(FontWeight.Medium)
              .fontColor(KColor.mut())
              .margin({ right: KSpace.S })
          }
          this.monthChip(row)
        }, (row: ContentArchiveMonthRow) => row.month)
      }
      .alignItems(VerticalAlign.Center)
    }
    .scrollable(ScrollDirection.Horizontal)
    .scrollBar(BarState.Off)
    .width('100%')
    .margin({ top: KSpace.L })
  }

  @Builder
  monthChip(row: ContentArchiveMonthRow) {
    Column() {
      Text(Archive.monthShort(row.month))
        .fontSize(KFont.meta())
        .fontWeight(this.selectedMonth === row.month ? FontWeight.Bold : FontWeight.Normal)
        .fontColor(this.selectedMonth === row.month ? KColor.surface() : KColor.ink())
      Text(`${row.count} 份`)
        .fontSize(KFont.caption())
        .fontColor(this.selectedMonth === row.month ? KColor.surface() : KColor.mut())
        .margin({ top: KSpace.HAIR })
    }
    .alignItems(HorizontalAlign.Center)
    .justifyContent(FlexAlign.Center)
    .height(KSize.TOUCH_MIN)
    .padding({ left: KSpace.M, right: KSpace.M })
    .margin({ right: KSpace.S })
    .backgroundColor(this.selectedMonth === row.month ? KColor.primary() : KColor.surface())
    .borderRadius(KRadius.S)
    .borderWidth(1)
    .borderColor(this.selectedMonth === row.month ? KColor.primary() : KColor.line())
    .onClick(() => {
      this.selectMonth(row.month);
    })
  }

  @Builder
  tierTag(importance: string, label: string) {
    Text(label)
      .fontSize(KFont.caption())
      .fontWeight(FontWeight.Medium)
      .fontColor(archiveTagInk(importance))
      .backgroundColor(archiveTagBg(importance))
      .borderRadius(KRadius.FULL)
      .padding({ left: KSpace.M, right: KSpace.M, top: KSpace.XS, bottom: KSpace.XS })
  }

  /** 核心考点卡：来源胶囊 + 发布日期 → 标题 → 要点 → 关键数字 → 主操作。 */
  @Builder
  coreCard(item: ContentArchiveItem) {
    Column() {
      Row() {
        this.tierTag(item.importance, '核心考点')
        Text(`${item.date} 发布`)
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .layoutWeight(1)
          .textAlign(TextAlign.End)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(item.title)
        .fontSize(KFont.titleS())
        .fontWeight(FontWeight.Medium)
        .lineHeight(KLine.tight())
        .fontColor(KColor.ink())
        .margin({ top: KSpace.M })
        .width('100%')

      if (item.gist.length > 0) {
        Text(item.gist)
          .fontSize(KFont.meta())
          .lineHeight(KLine.normal())
          .fontColor(KColor.sub())
          .margin({ top: KSpace.S })
          .width('100%')
      }

      // 关键数字：老档案没有这个字段 → 条件渲染，不补空行（与 Web 端一致）
      if (Archive.figuresLine(item).length > 0) {
        Text(Archive.figuresLine(item))
          .fontSize(KFont.caption())
          .lineHeight(KLine.tight())
          .fontColor(KColor.primaryText())
          .margin({ top: KSpace.S })
          .width('100%')
      }

      Row() {
        Text(item.lib)
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(item.readId.length > 0 ? '查看原文' : '查看官方原文')
          .fontSize(KFont.meta())
          .fontWeight(FontWeight.Medium)
          .fontColor(KColor.primaryText())
          .height(KSize.TOUCH_MIN)
          .padding({ left: KSpace.L, right: KSpace.L })
          .textAlign(TextAlign.Center)
          .borderRadius(KRadius.S)
          .borderWidth(1)
          .borderColor(KColor.primary())
          .onClick(() => {
            this.openItem(item);
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: KSpace.M })
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(KSpace.L)
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
    .borderWidth(1)
    .borderColor(KColor.line())
  }

  /**
   * 细则行：日期 + 标题 + 展开。
   * 高度用 minHeight 不用固定高 —— 台账标题长度不可控，硬卡高会把长标题压成省略号，
   * 而这一屏的用途就是"让你把标题看全、决定要不要点进去"。
   */
  @Builder
  restRow(item: ContentArchiveItem) {
    Column() {
      Row() {
        Text(Archive.dayOf(item.date))
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .width(KSpace.XXXL)
        Text(item.title)
          .fontSize(KFont.body())
          .fontColor(KColor.ink())
          .layoutWeight(1)
        Text(this.expandedUrl === item.url ? '收起' : '展开')
          .fontSize(KFont.caption())
          .fontColor(KColor.primaryText())
          .margin({ left: KSpace.S })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .constraintSize({ minHeight: KSize.TOUCH_MIN })
      .onClick(() => {
        this.toggleRow(item);
      })

      if (this.expandedUrl === item.url) {
        Column() {
          if (item.gist.length > 0) {
            Text(item.gist)
              .fontSize(KFont.meta())
              .lineHeight(KLine.normal())
              .fontColor(KColor.sub())
              .width('100%')
          }
          if (Archive.figuresLine(item).length > 0) {
            Text(Archive.figuresLine(item))
              .fontSize(KFont.caption())
              .lineHeight(KLine.tight())
              .fontColor(KColor.primaryText())
              .margin({ top: KSpace.S })
              .width('100%')
          }
          Row() {
            Text(item.readId.length > 0 ? '查看原文' : '查看官方原文')
              .fontSize(KFont.meta())
              .fontWeight(FontWeight.Medium)
              .fontColor(KColor.primaryText())
              .height(KSize.TOUCH_MIN)
              .padding({ left: KSpace.L, right: KSpace.L })
              .textAlign(TextAlign.Center)
              .borderRadius(KRadius.S)
              .borderWidth(1)
              .borderColor(KColor.primary())
              .onClick(() => {
                this.openItem(item);
              })
            Text(item.lib)
              .fontSize(KFont.caption())
              .fontColor(KColor.mut())
              .layoutWeight(1)
              .margin({ left: KSpace.M })
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .margin({ top: KSpace.M })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .padding({ bottom: KSpace.M })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  groupLabel(importance: string, label: string, note: string) {
    Row() {
      this.tierTag(importance, label)
      Text(note)
        .fontSize(KFont.caption())
        .fontColor(KColor.mut())
        .layoutWeight(1)
        .margin({ left: KSpace.S })
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  @Builder
  skeletonCard() {
    Column() {
      ForEach([0, 1, 2], () => {
        Column()
          .width('100%')
          .height(KSpace.XXXL)
          .backgroundColor(KColor.skeleton())
          .borderRadius(KRadius.S)
          .margin({ bottom: KSpace.S })
      }, (i: number) => `arc-sk-${i}`)
    }
    .width('100%')
    .padding(KSpace.L)
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
    .margin({ top: KSpace.L })
  }

  @Builder
  messageCard(title: string, detail: string, action: string) {
    Column() {
      Text(title)
        .fontSize(KFont.body())
        .fontWeight(FontWeight.Medium)
        .fontColor(KColor.ink())
        .width('100%')
      Text(detail)
        .fontSize(KFont.meta())
        .lineHeight(KLine.tight())
        .fontColor(KColor.sub())
        .margin({ top: KSpace.S })
        .width('100%')
      if (action.length > 0) {
        Button(action)
          .height(KSize.TOUCH_MIN)
          .margin({ top: KSpace.L })
          .onClick(() => {
            this.loadIndex();
          })
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(KSpace.L)
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.L)
    .borderWidth(1)
    .borderColor(KColor.line())
    .margin({ top: KSpace.L })
  }

  /** 本月台账主体。 */
  @Builder
  monthBody() {
    Column() {
      Row() {
        Text(this.monthTitle)
          .fontSize(KFont.titleM())
          .fontWeight(FontWeight.Bold)
          .fontColor(KColor.ink())
          .layoutWeight(1)
        if (this.monthCached) {
          Text('离线内容')
            .fontSize(KFont.caption())
            .fontColor(KColor.warnInk())
            .backgroundColor(KColor.warnSoft())
            .borderRadius(KRadius.FULL)
            .padding({ left: KSpace.M, right: KSpace.M, top: KSpace.XS, bottom: KSpace.XS })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(this.monthSummary)
        .fontSize(KFont.caption())
        .fontColor(KColor.mut())
        .margin({ top: KSpace.XS })
        .width('100%')

      if (this.coreItems.length > 0) {
        Column() {
          this.groupLabel(ArchiveTier.CORE, '核心考点', `本月 ${this.coreItems.length} 份 · 建议优先通读`)
          ForEach(this.coreItems, (item: ContentArchiveItem) => {
            this.coreCard(item)
          }, (item: ContentArchiveItem) => `core-${item.url}`)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .margin({ top: KSpace.L })
      }

      if (this.restItems.length > 0) {
        Column() {
          this.groupLabel(ArchiveTier.MEDIUM, '了解 · 细则', `本月 ${this.restItems.length} 份 · 有信息量但不成体系`)
          ForEach(this.restItems, (item: ContentArchiveItem) => {
            this.restRow(item)
            // ⚠️ 展开态必须写进 key：ForEach 只在 key 变化时重跑条目构建器，
            //    展开/收起只改 expandedUrl，不带进 key 会出现"点了展开没反应"。
            //    带进 key 后只有受影响的两条（原来展开的、新展开的）重建。
          }, (item: ContentArchiveItem) => `rest-${item.url}-${this.expandedUrl === item.url ? 'o' : 'c'}`)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .margin({ top: KSpace.L })
      }

      if (this.hintText.length > 0) {
        Text(this.hintText)
          .fontSize(KFont.meta())
          .fontColor(KColor.warnInk())
          .backgroundColor(KColor.warnSoft())
          .borderRadius(KRadius.S)
          .padding(KSpace.M)
          .margin({ top: KSpace.M })
          .width('100%')
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  @Builder
  body() {
    Column() {
      this.head()
      this.monthStrip()

      if (this.loading) {
        this.skeletonCard()
      } else if (this.errorText.length > 0) {
        this.messageCard('档案加载失败', this.errorText, '重试')
      } else if (this.months.length === 0) {
        this.messageCard('档案还是空的', '政策台账由 scripts/fetch-archive.py 按月抓取中国政府网文件库后生成。', '刷新')
      } else if (this.monthLoading) {
        this.skeletonCard()
      } else if (this.monthError.length > 0) {
        this.messageCard(`${Archive.monthLabel(this.selectedMonth)} 加载失败`, this.monthError, '重试')
      } else {
        this.monthBody()
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  build() {
    NavDestination() {
      Scroll() {
        // Scroll 只允许一个子组件，由外层 Column 兜住
        Column() {
          // 主题指纹层：字号 / 深色变化时整层重建
          // （令牌全局读 AppStorage，ArkUI 的依赖追踪看不到这条路径）
          ForEach([`${this.darkMode ? 'd' : 'l'}-${this.fontScale}`], () => {
            this.body()
          }, (key: string) => key)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .padding({ left: KSpace.PAGE, right: KSpace.PAGE, top: KSpace.M, bottom: KSpace.XXL })
      }
      .width('100%')
      .height('100%')
      .align(Alignment.Top)
      .scrollBar(BarState.Off)
      .backgroundColor(KColor.bg())
    }
    .title('政策档案')
    .backgroundColor(KColor.bg())
  }
}

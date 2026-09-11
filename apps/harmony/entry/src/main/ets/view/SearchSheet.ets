import { KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';

/** 一条可检索的文章索引（来自 manifest，含日期）。 */
export interface SearchHit {
  id: string;
  title: string;
  source: string;
  date: string;
}

/**
 * 跨日检索面板。
 *
 * ## 为什么要它
 * 首页只能按日期一天天翻，195 篇文章里想找"某天看到过的那篇"基本靠运气。
 * 这是真实痛点，而且**不需要任何服务端能力**：manifest 里已经带全量文章的
 * id / 标题 / 来源 / 日期，本地就能建索引、本地就能搜——零成本、离线可用。
 *
 * ## 边界（如实说明）
 * 当前只检索**标题与来源**，不做全文检索：全文需要把 195 篇正文都缓存下来
 * （约 2MB+），代价与收益不成正比。若要全文检索，应该在**构建期**产出
 * 一份轻量全文索引，而不是让端上拉全量正文。
 *
 * 命中为空时给**明确的空态**（而不是一片空白），并提示可试的方向。
 */
@Component
export struct SearchSheet {
  /** 全量索引，由首页在拿到 manifest 后一次性构建传入。 */
  hits: SearchHit[] = [];
  /** 选中某条结果（首页负责跳转）。 */
  onPick: (hit: SearchHit) => void = () => {
  };
  onClose: () => void = () => {
  };
  @State keyword: string = '';

  /** 大小写不敏感的子串匹配；命中标题或来源即算命中。 */
  private results(): SearchHit[] {
    const key: string = this.keyword.trim().toLowerCase();
    if (key.length === 0) {
      return [];
    }
    const out: SearchHit[] = [];
    for (const hit of this.hits) {
      if (hit.title.toLowerCase().includes(key) || hit.source.toLowerCase().includes(key)) {
        out.push(hit);
      }
    }
    return out;
  }

  @Builder
  hitRow(hit: SearchHit) {
    Row() {
      Column() {
        Text(hit.title)
          .fontSize(KFont.meta())
          .fontWeight(FontWeight.Medium)
          .fontColor(KColor.ink())
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')
        Text(`${hit.source} · ${hit.date}`)
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .margin({ top: KSpace.XS })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .constraintSize({ minHeight: KSize.TOUCH_MIN })
    .padding({ top: KSpace.M, bottom: KSpace.M })
    .onClick(() => {
      this.onPick(hit);
    })
  }

  build() {
    Column() {
      Row() {
        Text('检索往期')
          .fontSize(KFont.titleS())
          .fontWeight(FontWeight.Bold)
          .fontColor(KColor.ink())
        Blank()
        Text('关闭')
          .fontSize(KFont.meta())
          .fontColor(KColor.sub())
          .height(KSize.TOUCH_MIN)
          .padding({ left: KSpace.M, right: KSpace.M })
          .textAlign(TextAlign.Center)
          .onClick(() => {
            this.onClose();
          })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      TextInput({ text: this.keyword, placeholder: '输入标题或来源关键词' })
        .fontSize(KFont.meta())
        .height(KSize.TOUCH_MIN)
        .backgroundColor(KColor.surface())
        .borderRadius(KRadius.S)
        .margin({ top: KSpace.S })
        .onChange((value: string) => {
          this.keyword = value;
        })

      if (this.keyword.trim().length === 0) {
        // 空态一：还没输入
        Text(`可检索 ${this.hits.length} 篇往期文章（按标题与来源）`)
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .width('100%')
          .margin({ top: KSpace.M })
      } else if (this.results().length === 0) {
        // 空态二：无结果——给可执行的方向，而不是只报"没有"
        Text(`没有匹配「${this.keyword.trim()}」的文章。试试更短的关键词，或换来源名（如「人民网」）。`)
          .fontSize(KFont.meta())
          .lineHeight(KLine.tight())
          .fontColor(KColor.warnInk())
          .backgroundColor(KColor.warnSoft())
          .borderRadius(KRadius.S)
          .padding(KSpace.M)
          .width('100%')
          .margin({ top: KSpace.M })
      } else {
        Text(`命中 ${this.results().length} 篇`)
          .fontSize(KFont.caption())
          .fontColor(KColor.sub())
          .width('100%')
          .margin({ top: KSpace.M })
        List() {
          ForEach(this.results(), (hit: SearchHit) => {
            ListItem() {
              this.hitRow(hit)
            }
          }, (hit: SearchHit) => `${hit.date}-${hit.id}`)
        }
        .width('100%')
        .height('45%')
        .scrollBar(BarState.Off)
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: KSpace.L, right: KSpace.L, top: KSpace.M, bottom: KSpace.XXL })
    .backgroundColor(KColor.surfaceAlt())
    .borderRadius({ topLeft: KRadius.XL, topRight: KRadius.XL })
    .transition(TransitionEffect.OPACITY.combine(TransitionEffect.translate({ y: 60 })))
  }
}

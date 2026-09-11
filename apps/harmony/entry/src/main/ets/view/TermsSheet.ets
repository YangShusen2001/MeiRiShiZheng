import { Ai, AiResult } from '../service/Ai';
import { SavedTerm, Terms, TermsSyncResult } from '../service/Terms';
import { KColor, KFont, KLine, KRadius, KSize, KSpace } from '../theme/Tokens';

/**
 * 「我的术语」浮层。
 *
 * ## 为什么解析要按需触发而不是自动跑
 * 每条术语一次 AI 调用，服务端是**邀请码额度 + 10 次/分钟限流**。
 * 打开列表就把全部术语跑一遍，等于**一次点击烧掉整月额度** ✗
 * 所以：只显示已有的解析，没解析的给一个「AI 解析」按钮，用户点哪条算哪条。
 *
 * ## 空态不能只是"暂无数据"
 * 要告诉用户**怎么才会有**——从阅读页的 AI 解析下方收藏。
 */
@Component
export struct TermsSheet {
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;
  @State terms: SavedTerm[] = [];
  /** 正在解析的术语原文；空串表示没有进行中的请求。 */
  @State pending: string = '';
  @State errorText: string = '';
  /** 同步状态与结果文案。 */
  @State syncing: boolean = false;
  @State syncMessage: string = '';
  onClose: () => void = () => {
  };

  aboutToAppear(): void {
    this.reload();
  }

  private reload(): void {
    this.terms = Terms.list();
  }

  /** 上行到服务端。幂等，可重复点。 */
  private syncNow(): void {
    if (this.syncing || this.terms.length === 0) {
      return;
    }
    this.syncing = true;
    this.syncMessage = '';
    Terms.sync().then((result: TermsSyncResult) => {
      this.syncing = false;
      if (result.ok) {
        const skipped: string = result.skipped > 0 ? `，跳过 ${result.skipped} 条超长内容` : '';
        this.syncMessage = `已同步 ${result.uploaded} 条到云端收藏${skipped}。在网页端「收藏」页可以看到。`;
      } else {
        this.syncMessage = result.message;
      }
    });
  }

  private explainTerm(text: string): void {
    if (this.pending.length > 0) {
      return;
    }
    this.pending = text;
    this.errorText = '';
    Ai.explain(text).then((result: AiResult) => {
      this.pending = '';
      if (!result.ok) {
        this.errorText = result.text;
        return;
      }
      const list: SavedTerm[] = Terms.list();
      for (const item of list) {
        if (item.text === text) {
          Terms.save({
            text: item.text,
            articleId: item.articleId,
            note: item.note,
            explanation: result.text,
            savedAt: item.savedAt,
          });
          break;
        }
      }
      this.reload();
    });
  }

  @Builder
  termRow(item: SavedTerm) {
    Column() {
      Row() {
        Text(item.text)
          .fontSize(KFont.meta())
          .fontWeight(FontWeight.Medium)
          .fontColor(KColor.ink())
          .layoutWeight(1)
        if (item.explanation.length === 0) {
          Text(this.pending === item.text ? '解析中…' : 'AI 解析')
            .fontSize(KFont.caption())
            .fontColor(KColor.primaryText())
            .backgroundColor(KColor.primarySoft())
            .borderRadius(KRadius.S)
            .height(KSize.TOUCH_MIN)
            .padding({ left: KSpace.M, right: KSpace.M })
            .textAlign(TextAlign.Center)
            .onClick(() => {
              this.explainTerm(item.text);
            })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      if (item.explanation.length > 0) {
        Text(item.explanation)
          .fontSize(KFont.caption())
          .lineHeight(KLine.tight())
          .fontColor(KColor.sub())
          .margin({ top: KSpace.XS })
          .width('100%')
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding(KSpace.M)
    .backgroundColor(KColor.surface())
    .borderRadius(KRadius.S)
    .margin({ top: KSpace.S })
  }

  build() {
    Column() {
      Row() {
        Text('我的术语')
          .fontSize(KFont.titleS())
          .fontWeight(FontWeight.Bold)
          .fontColor(KColor.ink())
        Blank()
        if (this.terms.length > 0) {
          Text(this.syncing ? '同步中…' : '同步到云端')
            .fontSize(KFont.caption())
            .fontColor(KColor.primaryText())
            .height(KSize.TOUCH_MIN)
            .padding({ left: KSpace.M, right: KSpace.M })
            .textAlign(TextAlign.Center)
            .enabled(!this.syncing)
            .onClick(() => {
              this.syncNow();
            })
        }
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

      if (this.syncMessage.length > 0) {
        Text(this.syncMessage)
          .fontSize(KFont.caption())
          .lineHeight(KLine.tight())
          .fontColor(KColor.sub())
          .width('100%')
          .margin({ top: KSpace.S })
      }

      if (this.errorText.length > 0) {
        Text(this.errorText)
          .fontSize(KFont.caption())
          .lineHeight(KLine.tight())
          .fontColor(KColor.warnInk())
          .width('100%')
          .margin({ top: KSpace.S })
      }

      if (this.terms.length === 0) {
        Text('还没有收藏的术语。在阅读页点标注 → AI 解析下方有「收藏这个术语」。')
          .fontSize(KFont.caption())
          .lineHeight(KLine.tight())
          .fontColor(KColor.mut())
          .width('100%')
          .margin({ top: KSpace.L })
      } else {
        Text(`共 ${this.terms.length} 条`)
          .fontSize(KFont.caption())
          .fontColor(KColor.mut())
          .width('100%')
          .margin({ top: KSpace.M })
        ForEach(this.terms, (item: SavedTerm) => {
          this.termRow(item)
        }, (item: SavedTerm) => item.text)
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

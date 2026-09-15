import { KColor } from '../theme/Tokens';
import { HomePage } from '../view/HomePage';
import { ReadPage, ReadParam } from '../view/ReadPage';
import { ReviewPage } from '../view/ReviewPage';
/**
 * 应用根容器：用 Navigation + NavPathStack 管理页面栈。
 *
 * 注意：不使用已废弃的 `@ohos.router`（`router.pushUrl` 等），
 * 统一走组件导航（Navigation），便于后续加桌面卡片/实况窗时复用页面。
 * 页面注册在 `resources/base/profile/main_pages.json`。
 */
@Entry
@Component
struct Index {
  @Provide('navStack') navStack: NavPathStack = new NavPathStack();
  /**
   * 订阅主题与字号：@StorageLink 变化会触发本组件重建。
   * 注意——**每个页面都要自己订阅**：父组件重建不保证子组件的 build() 重跑，
   * 只靠这里订阅的话，切深色时页面颜色不会更新。
   */
  @StorageLink('darkMode') darkMode: boolean = false;
  @StorageLink('fontScale') fontScale: number = 1;

  @Builder
  pageMap(name: string, param: object) {
    if (name === 'read') {
      ReadPage({
        articleId: (param as ReadParam).articleId,
        dayIds: (param as ReadParam).dayIds,
      })
    } else if (name === 'review') {
      ReviewPage()
    }
  }

  build() {
    Navigation(this.navStack) {
      HomePage()
    }
    .title('每日时政')
    .titleMode(NavigationTitleMode.Mini)
    .mode(NavigationMode.Stack)
    .hideBackButton(true)
    .navDestination(this.pageMap)
    .backgroundColor(KColor.bg())
  }
}

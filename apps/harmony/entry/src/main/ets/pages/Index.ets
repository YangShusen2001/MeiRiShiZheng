import { HomePage } from '../view/HomePage';
import { ReadPage, ReadParam } from '../view/ReadPage';

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

  @Builder
  pageMap(name: string, param: object) {
    if (name === 'read') {
      ReadPage({ articleId: (param as ReadParam).articleId })
    }
  }

  build() {
    Navigation(this.navStack) {
      HomePage()
    }
    .title('考公云')
    .titleMode(NavigationTitleMode.Mini)
    .mode(NavigationMode.Stack)
    .hideBackButton(true)
    .navDestination(this.pageMap)
    .backgroundColor('#F5F1E8')
  }
}

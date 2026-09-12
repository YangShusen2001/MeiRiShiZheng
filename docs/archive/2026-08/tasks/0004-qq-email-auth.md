# TASK-0004：QQ 邮箱验证码认证

## Status

completed

## Owner

account-agent

## Dependencies

- 无

## Goal

用 QQ 邮箱验证码替换当前用户名密码登录，建立可撤销的安全 Session。

## Allowed Files

- `apps/api/**` 认证相关文件
- `packages/contracts/src/api.ts`
- `apps/web` 登录相关文件
- 认证迁移和测试

## Acceptance Criteria

- [x] 只接受 `@qq.com` 邮箱。
- [x] 验证码过期、重放和超限均失败。
- [x] 验证码请求不泄露邮箱是否存在。
- [x] Session 使用 HttpOnly、Secure、SameSite Cookie。
- [x] 登录、退出和会话查询有测试。
- [x] owner 使用 `device:`/`user:` namespace，登录时原子合并匿名收藏、划线和练习数据。

## Verification

```text
pnpm --filter @kaogong/api test
pnpm -r typecheck
pnpm --filter @kaogong/web test:e2e
```

## Handoff

```text
任务：TASK-0004 QQ 邮箱验证码认证
负责人：account-agent
修改文件：API 契约、认证/Session/身份路由、D1 Schema/迁移、登录页、导航和测试
实现内容：仅 QQ 邮箱、6 位验证码哈希、10 分钟有效期、5 次尝试、邮箱/IP/设备限流、首次自动用户、HttpOnly Session、登出；owner namespace 隔离；验证码消费、账号合并和 Session 创建原子提交
契约变化：移除公开用户名密码/JWT契约；新增 email code/session 契约
测试命令：pnpm -r test；pnpm -r typecheck；pnpm --filter @kaogong/web test:e2e
测试结果：当前仓库本地证据为 API 103/103、账号合并 16/16、迁移 8/8 和 API typecheck 通过；Web 单元 16/16、Astro check 0 errors/2 hints；未运行已部署 Worker 的验证码事务邮件和登录冒烟
已知问题：生产需同站点自定义域、AUTH_SECRET、MAIL_FROM、Email binding 和全部 D1 迁移
下游 Agent 注意事项：部署前应用当前完整 D1 迁移链，不能只应用历史 0008 迁移
是否满足验收标准：满足代码验收；外部配置待部署
```

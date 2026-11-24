# TCrB / personal blog

这是一个基于 Astro 的个人博客与项目展示站，当前版本已经完成基础视觉、路由和交互搭建。

## 预览

启动本地开发预览：

```bash
npm install
npm run dev
```

然后访问 `http://localhost:4321/`。

## 已完成

- 首页：个人介绍、最新文章、项目精选、联系入口
- 文章页：文章卡片、分类筛选、关键词搜索、文章详情与下一篇导航
- 项目页：项目列表与标签
- 实验室：实验项目入口卡片
- 关于页：个人介绍、能力与合作入口
- 全局深色模式切换、移动端导航、响应式布局
- Astro 静态生成，可直接部署到 Nginx、Caddy、GitHub Pages 或其他静态托管

## 目录约定

- `src/components/`：可复用的页头、页脚、文章卡片
- `src/pages/`：首页、文章、项目、实验室、关于页面
- `src/content/blog/`：文章资料，每篇文章一个 JSON 文件，按发布日期展示
- `src/data.ts`：文章索引、项目和实验数据
- `src/styles/global.css`：主题变量、组件样式与响应式布局
- `public/`：后续放置图片、图标、字体等静态资源
- `labs/`：独立实验项目

## 构建检查

```bash
npm run build
```

## 自动部署

合并到 `main` 后自动构建，阿里云 ECS 从 GitHub Releases 拉取并更新静态站。首次安装与验证见 [部署指南](deploy/README.md)。

## 站长登录

后台身份验证与静态站独立部署，仅允许指定的 GitHub 账号登录。登录用的 OAuth App 不申请仓库写权限。配置见 [站长登录指南](deploy/admin/README.md)。

可选的 [网页文章编辑器](deploy/admin/EDITOR.md) 支持新增、编辑和预览文章，使用独立的 GitHub App 创建 PR。合并后仍由原有 CI/CD 自动上线。

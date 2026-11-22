# 个人站项目文件框架

> 目标：以博客为主，提供项目展示和实验性互动项目。
> 推荐架构：Astro 主站 + Markdown/MDX 博客 + Astro Islands + 独立 Vite 实验项目。

## 1. 推荐目录结构

当前 `TCrB-web/` 文件夹就是个人站项目根目录，`D:\TCrB` 用于容纳多个项目。

```text
.
├── src/
│   ├── components/             # 可复用组件
│   │   ├── ui/                 # 按钮、卡片、标签等基础组件
│   │   ├── blog/               # 博客相关组件
│   │   └── interactive/         # 可嵌入文章或页面的交互组件
│   ├── content/
│   │   └── blog/               # Markdown/MDX 博客文章
│   ├── layouts/                # 页面布局
│   ├── pages/                  # 网站路由
│   │   ├── index.astro         # 首页
│   │   ├── about.astro         # 关于页
│   │   ├── blog/
│   │   │   ├── index.astro     # 博客列表
│   │   │   └── [...slug].astro # 博客文章详情
│   │   ├── projects/
│   │   │   └── index.astro     # 项目列表
│   │   └── lab/
│   │       └── index.astro     # 实验项目列表
│   ├── styles/                 # 全局样式和主题变量
│   └── config/                 # 站点信息、导航、社交链接等配置
│
├── labs/                       # 独立实验项目
│   ├── README.md
│   ├── _template/              # 新实验项目模板
│   └── <experiment-name>/      # 单个 Vite/React/Svelte 项目
│
├── public/
│   ├── images/                 # 图片资源
│   ├── icons/                  # 图标和 favicon
│   └── fonts/                  # 本地字体（如有需要）
│
├── scripts/                    # 构建、资源处理、数据生成脚本
├── tests/                      # 自动化测试和页面测试
├── astro.config.mjs            # Astro 配置
├── tsconfig.json               # TypeScript 配置
├── package.json                # 项目依赖和脚本
├── README.md                   # 项目说明
└── .gitignore
```

## 2. 页面规划

| 路径 | 用途 | 初始渲染方式 |
|---|---|---|
| `/` | 个人介绍、最新文章、精选项目 | 静态生成 |
| `/about/` | 关于我、技术栈、联系方式 | 静态生成 |
| `/blog/` | 博客文章列表 | 静态生成 |
| `/blog/<slug>/` | 文章详情 | 静态生成 |
| `/projects/` | 项目展示 | 静态生成 |
| `/lab/` | 实验项目入口 | 静态生成 |
| `/lab/<name>/` | 具体实验项目 | 独立构建或交互组件 |

## 3. 实验项目的使用规则

- 简单交互：放入 `src/components/interactive/`，作为 Astro Island 使用。
- 完整小应用：放入 `labs/<experiment-name>/`，使用独立 Vite 项目。
- 大型 WebGL、游戏、编辑器：优先独立部署，避免影响博客首页加载速度。
- 实验项目的截图、说明和文章可以放回主站的 `projects/` 或 `blog/` 页面。

## 4. 日常开发文件的存放规则

临时文件、测试输出、截图和实验中间产物统一放在项目根目录的：

```text
dev-workbench/
```

正式内容只有在确认后，才移动到 `src/`、`public/` 或 `labs/`。

## 5. 初期部署目标

```text
本地或 CI 构建
      ↓
生成静态文件
      ↓
Nginx/Caddy 提供服务
      ↓
需要动态能力时，再增加独立 API 和数据库
```

第一阶段不强制引入登录、数据库或 SSR，先保证博客、项目页和实验项目能够稳定发布。






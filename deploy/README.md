# 合并到 `main` 后自动部署博客

**PR 只检查；合并后，GitHub Actions 构建 Astro 静态站并发布到 [GitHub Releases](https://github.com/T-CrB/Blog/releases)。ECS 每分钟检查一次，下载新版本、验证 SHA-256 和页面后，再原子切换 Nginx 的站点目录。** 下载失败不会覆盖线上版本，下次检查会重试。连续合并时会跳过已经落后于 `main` 的构建，旧提交重跑不会覆盖已经上线的新版本。

ECS 需要能通过 HTTPS 下载 GitHub Release 资源。不需要 OSS、AccessKey、GitHub 个人令牌或新的 SSH 规则。本仓库是公开的，Release 中的构建包也是公开的，不能把私密文件放进 `public/` 或构建产物。

## 1. 在 GitHub 发布第一份构建

在 **Settings → Environments → production** 中将部署分支限制为 `main`，不要设置人工审批或等待时间（否则无法无人值守）。不用新增 Secrets 或 Variables。合并本工作流的 PR 后，在 **Actions → CI / CD** 查看 `main` 的运行，等 **Publish production build to GitHub Releases** 成功。也可在 `main` 上选择 **Run workflow** 重试当前提交。

打开 **Releases**，确认新的 `Blog production` 发布对应这次合并的提交。工作流会先上传三个附件到草稿，全部完成后才设为 Latest。不要手动把没有部署附件的 Release 标记为 Latest。Actions 发布成功只代表构建包可下载，不代表 ECS 已切换。

## 2. 首次安装 ECS 拉取服务

使用 Workbench 的管理员终端，确保有 `curl`、`python3` 和 `systemd`。以下命令适用于 Ubuntu + Nginx（包括宝塔管理的 Nginx）；root 终端可以省略 `sudo`。只从本仓库确认过提交的 Release 安装，不执行来历不明的脚本。

```bash
# REV 填第一步中对应已审阅合并提交的完整 40 位 SHA。
# SETUP_SHA256 填同一个 Release 说明中 “ECS setup SHA-256” 的 64 位值。
REV='<完整提交 SHA>'
SETUP_SHA256='<安装包 SHA-256>'
(
  set -eu
  umask 077
  cd "$(mktemp -d)"
  curl -fLsS --connect-timeout 8 --max-time 40 \
    -o tcrb-blog-ecs-setup.tar.gz \
    "https://github.com/T-CrB/Blog/releases/download/tcrb-blog-${REV}/tcrb-blog-ecs-setup.tar.gz"
  printf '%s  %s\n' "$SETUP_SHA256" tcrb-blog-ecs-setup.tar.gz | sha256sum -c -
  tar --no-same-owner -xzf tcrb-blog-ecs-setup.tar.gz
  sudo bash install-ecs.sh
  sudo systemctl start tcrb-web-deploy.service
  sudo journalctl -u tcrb-web-deploy.service -n 20 --no-pager
)
```

安装脚本复用现有 `blogdeploy` 用户，没有时创建一个不可登录的系统用户。拉取服务以此普通用户运行，不执行构建包中的文件。脚本只安装服务、在独立的 `/var/www/tcrb-web-deploy` 中准备新版本，不改旧站的目录或 Nginx 配置。

## 3. 验证后切换站点并开启自动更新

**看到日志 `Live Astro revision:` 且提交号正确后**，在宝塔或 Nginx 中把该静态站的根目录改成 `/var/www/tcrb-web-deploy/current`。先记下旧目录，保留现有域名、HTTPS 和站点配置。确保新目录按静态站提供，不启用 PHP 等脚本解释器；可参考相邻的 `nginx-tcrb-web.conf.example`，不用覆盖正在使用的整份配置。

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable --now tcrb-web-deploy.timer
systemctl list-timers tcrb-web-deploy.timer
```

浏览器打开首页、`/blog/` 和 `/_deploy-revision.txt`；最后一个应显示这次上线的合并提交。下一次合并后再检查此地址是否自动更新。完成验收后，可以删除不用的 `SERVER_*` GitHub Secrets。GitHub 不能下载时检查 `journalctl -u tcrb-web-deploy.service`，不要为此放开 SSH。若需要紧急回退，先运行 `sudo systemctl disable --now tcrb-web-deploy.timer`，再把静态站根目录恢复到之前验证过的目录并重载。历史部署目录按需手动清理，不要删除 `current` 指向的版本。

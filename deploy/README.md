# 合并到 `main` 后自动部署博客

**PR 只检查；合并后，GitHub Actions 构建 Astro 静态站并发布到 [GitHub Releases](https://github.com/T-CrB/Blog/releases)。ECS 每分钟检查一次，先验证清单确实由本仓库 `main` 上的生产工作流签署，再校验下载包的 SHA-256 和页面，最后原子切换站点目录。** 下载或验证失败不会覆盖线上版本。连续合并时会跳过已经落后于 `main` 的构建，旧提交重跑不会覆盖已经上线的新版本。

ECS 需要能访问 GitHub Release 和 GitHub CLI 使用的 Sigstore 信任根（`tuf-repo.github.com`、`tuf-repo-cdn.sigstore.dev`）。不需要 OSS、AccessKey、GitHub 个人令牌或新的 SSH 规则。Release 是公开的，不能把私密文件放进 `public/` 或构建产物。

## 1. 在 GitHub 发布第一份构建

先按[生产保护说明](admin/EDITOR.md#开启编辑前的生产保护)为 `main` 开启分支规则。在 **Settings → Environments → production** 中将部署分支限制为 `main`；不需要新增 Secrets 或 Variables。工作流只在受保护的 `main` 上由站长账号触发时发布。正常用站长身份合并即可，也可在 **Actions → CI / CD** 选择 `main` 上的 **Run workflow**。如启用文章编辑，仍须由站长本人审阅合并，不要配置机器人代合并。

打开 **Releases**，确认新的 `Blog production` 对应这次合并的提交。工作流会在两个签名证明都通过校验、五个附件全部上传后才把草稿设为 Latest。不要手动把未经验证的 Release 设置成 Latest。Actions 发布成功不代表 ECS 已切换。

## 2. 安装或升级 ECS 拉取服务

使用 Workbench 的管理员终端，确保有 `curl`、`python3`、`systemd` 和支持 `gh attestation verify --source-digest` 的 [GitHub CLI](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)。不用在 ECS 上执行 `gh auth login`。以下命令适用于 Ubuntu + Nginx（包括宝塔管理的 Nginx）；root 终端可以省略 `sudo`。只使用已审阅提交的发布，先验证安装包签名再解压执行。

```bash
# REV 填第一步中对应已审阅合并提交的完整 40 位 SHA。
REV='<完整提交 SHA>'
(
  set -eu
  umask 077
  cd "$(mktemp -d)"
  setup=tcrb-blog-ecs-setup.tar.gz
  proof="$setup.sigstore.jsonl"
  tag="https://github.com/T-CrB/Blog/releases/download/tcrb-blog-${REV}"
  for asset in "$setup" "$proof"; do
    curl --disable --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
      --connect-timeout 8 --max-time 40 -o "$asset" "$tag/$asset"
  done
  gh attestation verify "$setup" --bundle "$proof" --repo T-CrB/Blog \
    --cert-identity 'https://github.com/T-CrB/Blog/.github/workflows/ci-cd.yml@refs/heads/main' \
    --source-ref refs/heads/main --source-digest "$REV" --deny-self-hosted-runners
  tar --no-same-owner -xzf "$setup"
  sudo bash install-ecs.sh
  sudo systemctl start tcrb-web-deploy.service
  sudo journalctl -u tcrb-web-deploy.service -n 20 --no-pager
)
```

安装脚本复用现有 `blogdeploy` 用户，没有时创建一个不可登录的系统用户。拉取服务以此普通用户运行，不执行构建包中的文件。脚本不改 Nginx、不删除当前站点或历史版本。升级已有服务时先等第一份带证明的产物发布；旧的无签名 Release 不会被新版拉取器安装。若 ECS 有单独维护的下载兼容设置，升级前先确认新版拉取器也包含它们。

## 3. 验证后切换站点并开启自动更新

**看到日志 `Live Astro revision:` 且提交号正确后**，在宝塔或 Nginx 中把该静态站的根目录改成 `/var/www/tcrb-web-deploy/current`。先记下旧目录，保留现有域名、HTTPS 和站点配置。确保新目录按静态站提供，不启用 PHP 等脚本解释器；可参考相邻的 `nginx-tcrb-web.conf.example`，不用覆盖正在使用的整份配置。

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable --now tcrb-web-deploy.timer
systemctl list-timers tcrb-web-deploy.timer
```

浏览器打开首页、`/blog/` 和 `/_deploy-revision.txt`；最后一个应显示这次上线的合并提交。已有站点不需要再次切换 Nginx，确认定时器启用后可以用下面的只读检查复核当前版本：

```bash
sudo runuser -u blogdeploy -- /usr/bin/python3 -B /usr/local/lib/tcrb-web-deploy/pull.py --verify-current
```

下一次合并后再检查此地址是否自动更新。完成验收后，可以删除不用的 `SERVER_*` GitHub Secrets。GitHub 不能下载时检查 `journalctl -u tcrb-web-deploy.service`，不要为此放开 SSH。若需要紧急回退，先运行 `sudo systemctl disable --now tcrb-web-deploy.timer`，再把静态站根目录恢复到之前验证过的目录并重载。历史部署目录按需手动清理，不要删除 `current` 指向的版本。

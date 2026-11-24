# 博客后台：只验证站长身份

公开博客继续使用 Astro 静态构建。`/admin/` 单独交给 ECS 上的登录服务，只允许 `T-CrB` 的 GitHub 数字账号 ID `224936987`。这一版只有登录、身份确认和退出；不申请仓库权限，不提供编辑或发布，也不改 GitHub Actions 到 ECS 的静态站部署链路。

## 注册专用于登录的 GitHub OAuth App

在自己的 GitHub 账号里打开 **Settings → Developer settings → OAuth Apps → New OAuth App**，填这三项：

| 字段 | 值 |
| --- | --- |
| Application name | `TCrB Blog Admin` |
| Homepage URL | `https://47.110.252.64/` |
| Authorization callback URL | `https://47.110.252.64/admin/callback` |

不要启用 Device Flow。注册后复制 **Client ID**，点击 **Generate a new client secret**。Secret 只在后面的 ECS 隐藏输入提示中粘贴；不要发到聊天、GitHub Actions Secrets 或仓库。不要复用申请过仓库权限的其他应用。

## 部署到 ECS

在 Windows PowerShell 将本次改动里的后台文件复制到自己的服务器（不需要用 GitHub 代理连接 ECS）：

```powershell
Set-Location 'D:\TCrB\TCrB-web'
scp -r .\deploy\admin root@47.110.252.64:/root/
```

在 ECS 的 root 终端安装。需要 Ubuntu 现有的 Python 3 和 `python3-venv`；若尚未安装后者，先运行 `apt-get update && apt-get install -y python3-venv`。安装会从 PyPI 下载并校验固定版本的 Waitress，生成只在服务器上保存的配置，**不会改 Nginx**。

```bash
bash /root/admin/install-ecs.sh
journalctl -u tcrb-blog-admin.service -n 20 --no-pager
curl --noproxy '*' -fsS -I -H 'Host: 47.110.252.64' http://127.0.0.1:8765/admin/
```

最后一条应返回 `200`。`8765` 只监听服务器本机，**不要给安全组开放这个端口**。ECS 运行后台时需要能访问 `github.com` 和 `api.github.com` 的 HTTPS，不要把 Windows 本机的 `127.0.0.1:7900` 代理配置到 ECS。

备份并打开当前博客的 Nginx 配置：

```bash
SITE=/www/server/panel/vhost/nginx/tcrb-blog.conf
blog_nginx() { /www/server/nginx/sbin/nginx -c /www/server/nginx/conf/nginx.conf "$@"; }
BACKUP=$(mktemp -d /root/tcrb-blog-pre-admin.XXXXXXXX) &&
  cp -p -- "$SITE" "$BACKUP/tcrb-blog.conf" &&
  printf '备份位置：%s/tcrb-blog.conf\n' "$BACKUP" &&
  cat /root/admin/nginx-admin.conf.example && nano "$SITE"
```

只把打印的 `location ^~ /admin/ { ... }` 贴进**含 `listen 443 ssl` 的博客 `server` 块**中，与原有 `location /` 并列。不要改 80 端口那段、证书验证路径或博客根目录。保存后运行 `blog_nginx -t && blog_nginx -s reload`。如检查报错，先不要重载；可在同一终端用 `cp -p -- "$BACKUP/tcrb-blog.conf" "$SITE"` 恢复备份。

## 验收

打开 `https://47.110.252.64/admin/`。无痕窗口应只能看到 GitHub 登录按钮，公开的 `/blog/` 仍可直接访问；用 `T-CrB` 登录后应看到「站长 · 已验证」；用其他 GitHub 账号登录应看到「没有站长权限」（`403`）。退出站长账号后刷新后台，应回到登录页。服务重启或会话过期后需要重新登录。

GitHub 返回的访问令牌只在服务器验证本次账号身份时使用，不写入会话或构建产物。OAuth 回调和站长会话均不缓存。后续加入任何编辑、保存或发布接口时，都必须在服务端检查站长权限，不能依赖隐藏按钮。单独停止后台服务或撤掉 Nginx 的后台转发规则，不会影响博客的静态发布。

## 排查登录回调失败

如果授权返回后显示「暂时无法登录」，从 `/admin/` 重新点一次「用 GitHub 登录」，不要刷新旧的回调页。然后在 ECS 查看最近一条失败日志：

```bash
journalctl -u tcrb-blog-admin.service -n 30 --no-pager | grep -F 'GitHub sign-in failed' | tail -n 1
```

`stage=token_exchange` 表示卡在 GitHub 换取令牌；`stage=user_lookup` 表示卡在查询 GitHub 账号。`timeout`、`dns_error`、`tls_error` 优先检查 ECS 到 GitHub 的网络、DNS 或证书；`incorrect_client_credentials` 核对 ECS 中保存的 Client ID 和 Client Secret 是否属于同一个 OAuth App；`unexpected_scope` 表示后台拒绝了带额外权限的令牌，不要为了登录而放开权限。日志只记录阶段及固定的原因标签，不记录密钥、授权码或令牌。

参考：[创建 GitHub OAuth App](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app) · [GitHub OAuth 安全实践](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/best-practices-for-creating-an-oauth-app)

# 网页文章编辑器

通过 `/admin/` 登录站长账号后，可以新增文章、编辑 `main` 上的既有文章、预览，或创建 GitHub PR。只处理 `src/content/blog/` 下的文章文件；由站长在 GitHub 审阅并合并后才会自动部署。编辑器不会自动保存草稿。在登录仍有效时，表单过期会保留输入，可以重新预览后再提交；如果之前提交过，先在 GitHub 确认未创建重复 PR。

## 开启编辑前的生产保护

1. 在仓库 **Settings → Rules → Rulesets** 创建针对 `main` 的 **Active** 分支规则集。启用 **Restrict updates**、**Require a pull request before merging**、**Restrict deletions** 和 **Block force pushes**。只把 **Repository admins** 加到豁免列表，模式设为 **For pull requests only**，以便站长能合并但不能直接推送。可给必检项添加 `Build Astro site`；不要启用要求压缩合并的线性历史规则。不要把编辑 App、普通写权限角色或其他自动化加入豁免列表。发布工作流要求 `main` 受保护且由站长触发；编辑器在缺少更新限制或 PR 规则时拒绝创建 PR。
2. 先用普通合并提交合并登录 PR，再合并包含编辑器和产物校验的 PR。按[静态站部署说明](../README.md)发布第一份带证明的生产产物，升级 ECS 拉取器，并确认它正在运行且已验证签名。启用脚本会在安装编辑私钥前检查拉取服务和当前版本。
3. 完成以上两步后再安装下方的 GitHub App。App 的写权限不是文件路径级别；它仍可管理仓库 Release 资源，但 ECS 会拒绝没有指定生产工作流签名的清单。只升级后台而不配置编辑凭据时，站长登录照常可用。

## 创建只用于文章 PR 的 GitHub App

在 GitHub 个人设置的 **Developer settings → GitHub Apps → New GitHub App** 创建一个独立应用（不是现有的 OAuth App）。取一个可辨识的名字，例如 `TCrB Blog Article Editor`，首页填 `https://47.110.252.64/`；不填登录回调、不启用用户授权流程和 Webhook。将安装范围选为 **Only on this account**。仓库权限只加 **Contents: Read and write**、**Pull requests: Read and write**，保留默认的 **Metadata: Read**，不要给 Workflows 或 Administration 写权限。

应用建好后，从 **Install App** 安装到 `T-CrB`，**只选择 `T-CrB/Blog`**。在应用详情记录 **Client ID**，从对应安装设置地址末尾取得数字 **Installation ID**。在应用详情点 **Generate a private key** 下载 PEM 文件。这个 PEM 和站长登录的 Client Secret 都不要提交到 GitHub、发到聊天或放进 Actions Secrets。后台用 PEM 签发短期安装令牌，明确限制到 `Blog` 与上面的两项写权限；不会把令牌发送到浏览器。

## 升级并启用 ECS 后台

在 Windows PowerShell，把合并后的后台代码上传到 ECS。另把下载的私钥文件放在工作区以外，切到下载目录后把文件复制到目标位置；把示例中的 `downloaded-key.private-key.pem` 换成实际文件名：

```powershell
Set-Location 'D:\TCrB\TCrB-web'
scp -r .\deploy\admin root@47.110.252.64:/root/
Set-Location "$HOME\Downloads"
scp .\downloaded-key.private-key.pem root@47.110.252.64:/root/blog-editor.private-key.pem
```

在 ECS 的 `root` 终端升级原服务。安装脚本会保留之前的 OAuth 配置；启用脚本会提示输入 **新 GitHub App** 的 Client ID 和 Installation ID：

```bash
chmod 600 /root/blog-editor.private-key.pem &&
  bash /root/admin/install-ecs.sh &&
  bash /root/admin/enable-editor-ecs.sh /root/blog-editor.private-key.pem
```

确认已按[登录部署说明](README.md)为 `/admin/login` 安装限流配置。在现有的 HTTPS `location ^~ /admin/` 中，把 `client_max_body_size` 改为 `256k`，`proxy_read_timeout` 改为 `95s`。不新增重复的 `location`，不碰 80、证书验证或静态站路径。配置位于 `/www/server/panel/vhost/nginx/tcrb-blog.conf`，先备份再改，检查成功才重载：

```bash
/www/server/nginx/sbin/nginx -c /www/server/nginx/conf/nginx.conf -t &&
  /www/server/nginx/sbin/nginx -c /www/server/nginx/conf/nginx.conf -s reload
```

重新登录后，点「管理文章」。先打开一篇现有文章做预览，再提交一个可检查的 PR，确认差异只有一篇文章，没有直接写 `main`。最后由你决定是否合并。验证通过后可删除 `/root/blog-editor.private-key.pem` 的上传副本；后台只使用 `/etc/tcrb-blog-admin/` 下受限的副本。端口 `8765` 仍仅在本机监听，不对公网开放，也不使用 Windows 本机 `7900` 代理。

## 停用编辑但保留登录

移走 `/etc/systemd/system/tcrb-blog-admin.service.d/editor.conf`，再执行 `systemctl daemon-reload && systemctl restart tcrb-blog-admin.service`。如不再使用，在 GitHub 撤销该私钥或卸载文章编辑应用。不要删除原来登录用的 OAuth App。

参考：[GitHub App 安装身份认证](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)。

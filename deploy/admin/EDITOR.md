# 网页文章编辑器

通过 `/admin/` 登录站长账号后，可以新增文章、编辑 `main` 上的既有文章、预览，或创建 GitHub PR。只处理 `src/content/blog/` 下的文章文件，不修改网页模板、工作流、线上文件或 `main`。PR 提交后仍要你在 GitHub 合并，才会走原来的自动部署。编辑器不会自动保存未提交的草稿；预览或报错时，当前表单会保留输入。

先合并包含文章文件和编辑器的 PR，再在 ECS 启用编辑。只升级后台但不配置编辑凭据时，原有站长登录照常可用。

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

在现有的 HTTPS `location ^~ /admin/` 中，把 `client_max_body_size 2k;` 改成 `client_max_body_size 256k;`，把 `proxy_read_timeout 25s;` 改成 `proxy_read_timeout 65s;`。不新增重复的 `location`，不碰 80、证书验证或静态站路径。配置位于 `/www/server/panel/vhost/nginx/tcrb-blog.conf`，先备份再改，检查成功才重载：

```bash
/www/server/nginx/sbin/nginx -c /www/server/nginx/conf/nginx.conf -t &&
  /www/server/nginx/sbin/nginx -c /www/server/nginx/conf/nginx.conf -s reload
```

重新登录后，点「管理文章」。先打开一篇现有文章做预览，再提交一个可检查的 PR，确认差异只有一篇文章，没有直接写 `main`。最后由你决定是否合并。验证通过后可删除 `/root/blog-editor.private-key.pem` 的上传副本；后台只使用 `/etc/tcrb-blog-admin/` 下受限的副本。端口 `8765` 仍仅在本机监听，不对公网开放，也不使用 Windows 本机 `7900` 代理。

## 停用编辑但保留登录

移走 `/etc/systemd/system/tcrb-blog-admin.service.d/editor.conf`，再执行 `systemctl daemon-reload && systemctl restart tcrb-blog-admin.service`。如不再使用，在 GitHub 撤销该私钥或卸载文章编辑应用。不要删除原来登录用的 OAuth App。

参考：[GitHub App 安装身份认证](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)。

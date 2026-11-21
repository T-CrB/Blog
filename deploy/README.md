# GitHub 与服务器部署说明

当前项目是 Astro 静态站，推荐使用「GitHub Actions 构建 + SSH/Rsync 同步到 Ubuntu/Nginx」的方式部署。

## 一、GitHub 仓库

在 GitHub 新建一个空仓库，然后在本地执行：

```bash
git init -b main
git add .
git commit -m "chore: initial personal site"
git remote add origin <你的 GitHub 仓库地址>
git push -u origin main
```

如果本地已经初始化过 Git，只需要添加远程地址并推送即可。

## 二、服务器准备

以 Ubuntu + Nginx 为例：

```bash
sudo apt update
sudo apt install -y nginx rsync
sudo mkdir -p /var/www/tcrb-web
sudo chown -R $USER:$USER /var/www/tcrb-web
```

复制 `deploy/nginx-tcrb-web.conf.example` 到 Nginx 配置目录，修改域名后启用：

```bash
sudo cp deploy/nginx-tcrb-web.conf.example /etc/nginx/sites-available/tcrb-web
sudo ln -s /etc/nginx/sites-available/tcrb-web /etc/nginx/sites-enabled/tcrb-web
sudo nginx -t
sudo systemctl reload nginx
```

正式环境建议再使用 Certbot 配置 HTTPS。

## 三、GitHub Environment 与 Secrets

在仓库的 `Settings → Environments` 中创建 `production`，然后添加以下 Environment secrets：

- `SERVER_HOST`：服务器 IP 或域名
- `SERVER_PORT`：SSH 端口，默认 `22`
- `SERVER_USER`：用于部署的 Linux 用户
- `SERVER_PATH`：部署目录，例如 `/var/www/tcrb-web`
- `SERVER_SSH_KEY`：部署用户对应的私钥
- `SERVER_KNOWN_HOSTS`：服务器的 SSH 主机指纹

主机指纹可以在可信环境中执行：

```bash
ssh-keyscan -H <服务器域名或 IP>
```

不要把私钥直接写入仓库文件，也不要把这些值放进普通源码变量。

## 四、自动化流程

`.github/workflows/ci-cd.yml` 会执行：

- Pull Request：安装依赖并运行 `npm run build`
- 推送到 `main`：构建静态站、保存 `dist/` 构建产物，然后通过 SSH/Rsync 发布到服务器
- 手动运行：在 GitHub Actions 页面执行 `workflow_dispatch`

生产部署使用 GitHub 的 `production` Environment，可以在 GitHub 中增加审批规则，避免每次推送直接发布。

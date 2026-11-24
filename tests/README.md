# 测试

本地运行部署和后台登录测试（仅用 Python 标准库，不会访问 GitHub 或改动服务器；签名测试需要 OpenSSL）：

```bash
python -B -m unittest discover -s tests
```

部署测试覆盖构建包校验、受限解压、生产证明校验的边界、原子切换、失败保留线上版本和旧版本保护；登录测试覆盖站长身份、旧回调、登录缓存满载、网络失败和退出。GitHub Actions 还会运行 `npm run build`，在生产发布前用 GitHub CLI 验证实际签名。

编辑器测试使用模拟 GitHub API，覆盖游客限制、过期表单恢复、正文保留、旧版本冲突和 `main` 规则检查，并确认只能在专用分支生成文章提交和 PR。

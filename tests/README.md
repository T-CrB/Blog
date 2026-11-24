# 测试

本地运行部署和后台登录测试（仅用 Python 标准库，不会访问 GitHub 或改动服务器）：

```bash
python -B -m unittest discover -s tests
```

部署测试覆盖构建包校验、受限解压、原子切换、失败保留线上版本和旧版本保护；登录测试模拟 GitHub 响应，覆盖游客、站长、非站长、过期/重复回调、网络失败和退出。GitHub Actions 还会运行 `npm run build`。

# 测试

本地运行部署测试（仅用 Python 标准库，不会访问 GitHub 或改动服务器）：

```bash
python -B -m unittest discover -s tests -p 'test_github_deploy.py'
```

测试包括构建包校验、受限解压、原子切换、网络/包错误保留线上版本、重复拉取和旧版本保护。GitHub Actions 还会运行 `npm run build`。

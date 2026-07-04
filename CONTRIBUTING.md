# 贡献指南

感谢你对 ZFundPilot 的兴趣！欢迎提交 Issue 或 Pull Request。

## 开发环境

```bash
git clone https://github.com/Euzohn/ZFundPilot.git
cd ZFundPilot
pip install -e ".[dev]"
```

## 代码规范

- 使用 **Ruff** 进行代码检查与格式化：`ruff check --fix . && ruff format .`
- 测试：`pytest`
- 提交前请确保 `ruff check .` 和 `pytest` 均通过

## 项目结构

```text
src/zfundpilot/     # 包源码
tests/              # 测试
app.py              # Streamlit 启动入口（薄壳）
```

## 提交规范

- Commit message 使用中文或英文均可，保持简洁
- PR 请描述清楚改动内容与动机

## 设计原则

ZFundPilot 只做数据分析与风险管理，**不做**自动交易、不预测涨跌、不构成投资建议。
贡献内容应与这一原则一致。

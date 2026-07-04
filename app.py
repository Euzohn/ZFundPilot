"""ZFundPilot 启动入口。

运行：
    streamlit run app.py
"""
import os
import sys

# 开发模式：未 pip install -e . 时自动将 src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from zfundpilot.app import main

if __name__ == "__main__":
    main()

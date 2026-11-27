"""aiui —— 自然语言驱动的 UI 自动化测试框架。

模块地图：
    planning  需求 -> 计划 -> 校验 -> 编译
    locator   三级定位（缓存 / 规则 / AI）
    actions   10 类动作的实现
    executor  执行主循环
    guardrail 高风险拦截与模型能力边界
    evidence  6 类证据采集
    llm       DeepSeek / Fake 网关
"""

__version__ = "0.1.0"

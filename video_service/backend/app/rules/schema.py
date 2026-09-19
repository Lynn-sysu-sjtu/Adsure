"""词库 schema 声明。

`lexicon/` 目录下放着两种结构完全不同的词库，各由不同的加载器负责：

    terms         L1 / L2 / L3 —— 词面命中型，由 matcher.Lexicon 加载
    requirements  L4          —— 必备要素型（没有词面可匹配），由 mandatory 加载

每份词库必须在 `meta.kind` 里声明自己属于哪一种。**不设默认值是刻意的**：
新增词库时忘了声明，应当在加载阶段立刻失败，而不是被当成词面型
静默解析出一堆 KeyError —— 那种报错完全指不向真正的原因。

常量单独放在这里，而不是搁在某个加载器里，是为了让两个加载器
平等地依赖它，避免 mandatory 为了一个常量去 import AC 自动机模块。
"""

KIND_TERMS = "terms"
KIND_REQUIREMENTS = "requirements"

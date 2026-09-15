"""前端排版守门测试：防止 `web/src` 再被压成「多语句单行」（P1-5-1）。

设计文档章节：不属于设计文档——这是工程化守门，对应 2026-09-15 的 P1-5-1。

背景（P1-5-1 审计时的实测值）：`web/src/styles.css` 当时只有 59 行，最长一行
**2950 个字符**（十几条 CSS 规则挤在一行），`IncidentForm.vue` 672 字符、
`ExecutionTrace.vue` 457 字符、`UserMenu.vue` 225 字符、`LoginForm.vue` 203 字符、
`AppLayout.vue` 201 字符，`LoginView.vue` 把三条 `const`、一个 `async function`
和 `try/catch` 各压成一行。排版不影响运行，但不能评审、也不能 diff。

四条守门规则（都只描述「压行」的充分特征，故意不做完整语法解析，避免误伤正常写法）：

- **R1** 单行不超过 200 字符。这只是兜底：真正的判据是 R2–R4，R1 拦的是"整块塞进一行"。
- **R2** CSS（`.css` 文件与 `.vue` 的 `<style>` 块）：一行最多一个 `;`、一个 `{`、一个 `}`，
  且不允许 `{` 与 `}` 同行——即「一条规则、一条声明各占一行」。
- **R3** 模板：同一行不允许「结束标签紧跟开始标签」（`</a><b`）——这是「多个兄弟元素
  挤在一行」的特征。**不**禁止 `</a></b>`（内联元素的嵌套收尾）和「标签内属性换行」，
  因为这两者在 Vue `whitespace: 'condense'` 下不改变渲染结果：P1-5-1 用
  `@vue/compiler-sfc` 把模板编译成 render 函数后逐字节比对验证过（含反例：
  「元素与文本之间的换行会多出一个空格」）。
- **R4** 脚本（`.ts` 文件与 `.vue` 的 `<script>` 块）：同一行不允许两个用 `;` 连接的语句。

`test_rules_flag_compressed_input_and_accept_expanded_input` 用合成样例证明这四条
规则既抓得到压缩写法、又不误报展开写法——测试自身的反证，避免规则被改成永远通过。
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = PROJECT_ROOT / "web" / "src"
MAX_LINE_LENGTH = 200

SOURCES = sorted(path for path in WEB_SRC.rglob("*") if path.suffix in {".vue", ".ts", ".css"})

#: 「结束标签紧跟开始标签」= 同一行里两个相邻的兄弟元素。
_SIBLING_TAGS = re.compile(r"</[A-Za-z][\w-]*>\s*<[A-Za-z]")
#: 「用分号连接的两个语句」：分号后面还是一个语句/表达式的开头。
_JOINED_STATEMENTS = re.compile(
    r";\s*(?:const|let|var|if|for|while|try|return|throw|await|async|function"
    r"|[A-Za-z_$][\w$]*\s*[.(=])"
)
_BLOCK = {
    "style": re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL),
    "script": re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL),
}


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _lines(text: str) -> list[tuple[int, str]]:
    return list(enumerate(text.splitlines(), start=1))


def _vue_block_lines(text: str, kind: str) -> list[tuple[int, str]]:
    """取 `.vue` 里某个块的行，并保留它在整个文件中的真实行号（报告用）。"""
    found: list[tuple[int, str]] = []
    for match in _BLOCK[kind].finditer(text):
        first_line = text.count("\n", 0, match.start(1)) + 1
        found.extend(
            (first_line + offset, line) for offset, line in enumerate(match.group(1).splitlines())
        )
    return found


def find_long_lines(text: str) -> list[tuple[int, str]]:
    """R1：返回超过 `MAX_LINE_LENGTH` 的行（恰好等于上限算通过）。"""
    return [(number, line) for number, line in _lines(text) if len(line) > MAX_LINE_LENGTH]


def _mask_css_literals(line: str) -> str:
    """去掉字符串与括号内的内容再计数。

    否则 `@import url('...wght@400;500&...')` 会因为 URL 里的 `;` 被误判成
    「一行多条声明」（P1-5-1 实测踩到），`content: "a;b"` 同理。
    """
    masked = re.sub(r"'[^']*'", "''", line)
    masked = re.sub(r'"[^"]*"', '""', masked)
    return re.sub(r"\([^()]*\)", "()", masked)


def find_compressed_css(text: str) -> list[tuple[int, str]]:
    """R2：返回把多条规则/多条声明挤在一行的 CSS 行。"""
    compressed = []
    for number, line in _lines(text):
        code = _mask_css_literals(line)
        if (
            code.count(";") > 1
            or code.count("{") > 1
            or code.count("}") > 1
            or ("{" in code and "}" in code)
        ):
            compressed.append((number, line))
    return compressed


def find_packed_tags(text: str) -> list[tuple[int, str]]:
    """R3：返回同一行里塞了相邻兄弟元素的行。"""
    return [(number, line) for number, line in _lines(text) if _SIBLING_TAGS.search(line)]


def find_joined_statements(text: str) -> list[tuple[int, str]]:
    """R4：返回把两个语句用分号挤在一行的脚本行。"""
    return [(number, line) for number, line in _lines(text) if _JOINED_STATEMENTS.search(line)]


def _report(rule: str, problems: list[str], hint: str) -> str:
    return (
        f"{rule} 未通过：{len(problems)} 处。\n"
        f"{hint}\n" + "\n".join(f"  - {problem}" for problem in problems)
    )


def test_frontend_sources_are_discovered():
    """防空跑：路径或后缀写错时，下面四条规则会因为「没有文件」而全部通过。"""
    assert WEB_SRC.is_dir(), f"前端源码目录不存在：{WEB_SRC}"
    assert len(SOURCES) >= 20, f"只发现 {len(SOURCES)} 个前端源文件，路径大概率不对"
    assert {path.suffix for path in SOURCES} == {".vue", ".ts", ".css"}
    assert (WEB_SRC / "styles.css").is_file()


def test_no_line_is_longer_than_the_limit():
    """R1：单行不超过 200 字符（P1-5-1 之前 styles.css 最长行是 2950 字符）。"""
    problems = [
        f"{_relative(path)}:{number} 长度 {len(line)}"
        for path in SOURCES
        for number, line in find_long_lines(path.read_text(encoding="utf-8"))
    ]
    assert not problems, _report("R1（单行长度上限）", problems, "请把长行按元素/规则/语句拆开。")


def test_css_rules_and_declarations_are_expanded_one_per_line():
    """R2：CSS 一条规则、一条声明各占一行。"""
    problems = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".css":
            found = find_compressed_css(text)
        elif path.suffix == ".vue":
            found = [
                (number, line)
                for block in _BLOCK["style"].finditer(text)
                for number, line in find_compressed_css(block.group(1))
            ]
        else:
            continue
        problems.extend(f"{_relative(path)}:{number} {line.strip()[:70]}" for number, line in found)
    assert not problems, _report("R2（CSS 排版）", problems, "每个选择器块与每条声明各占一行。")


def test_template_siblings_are_not_packed_on_one_line():
    """R3：模板不把多个兄弟元素塞进同一行。"""
    problems = [
        f"{_relative(path)}:{number} {line.strip()[:70]}"
        for path in SOURCES
        if path.suffix == ".vue"
        for number, line in find_packed_tags(path.read_text(encoding="utf-8"))
    ]
    assert not problems, _report(
        "R3（模板排版）", problems, "兄弟元素各占一行；元素与文本之间的空白必须留在原行。"
    )


def test_script_statements_are_not_joined_by_semicolons():
    """R4：脚本不把两个语句用 `;` 挤在一行。"""
    problems = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".ts":
            found = find_joined_statements(text)
        elif path.suffix == ".vue":
            found = _vue_block_lines(text, "script")
            found = [(number, line) for number, line in found if _JOINED_STATEMENTS.search(line)]
        else:
            continue
        problems.extend(f"{_relative(path)}:{number} {line.strip()[:70]}" for number, line in found)
    assert not problems, _report("R4（脚本排版）", problems, "每个语句各占一行。")


def test_rules_flag_compressed_input_and_accept_expanded_input():
    """测试自身的反证：四条规则抓得到压缩写法，也不会误报展开写法。"""
    compressed_css = ".a { color: red; }.b { margin: 0; }"
    expanded_css = ".a {\n  color: red;\n}\n\n.b {\n  margin: 0;\n}"
    compressed_tags = '<div class="a"><span>1</span><h3>2</h3></div>'
    expanded_tags = '<div class="a">\n  <span>1</span>\n  <h3>2</h3>\n</div>'
    compressed_js = "const a = f(); const b = g()"
    expanded_js = "const a = f()\nconst b = g()"

    assert find_compressed_css(compressed_css), "R2 没有抓到压行的 CSS"
    assert find_packed_tags(compressed_tags), "R3 没有抓到压行的模板"
    assert find_joined_statements(compressed_js), "R4 没有抓到压行的脚本"
    assert find_long_lines("x" * (MAX_LINE_LENGTH + 1)), "R1 没有抓到超长行"

    assert not find_compressed_css(expanded_css), "R2 误报了展开后的 CSS"
    assert not find_packed_tags(expanded_tags), "R3 误报了展开后的模板"
    assert not find_joined_statements(expanded_js), "R4 误报了展开后的脚本"
    assert not find_long_lines("x" * MAX_LINE_LENGTH), "R1 在恰好等于上限时误报"

    # 反例：URL/字符串里的 `;` 不算「多声明」（P1-5-1 实测踩过这个误报）。
    fonts_url = (
        "@import url('https://fonts.googleapis.com/css2"
        "?family=DM+Mono:wght@400;500;700&display=swap');"
    )
    assert not find_compressed_css(fonts_url), "R2 把 URL 里的分号误判成多条声明"
    assert not find_compressed_css('.a {\n  content: "x;y";\n}'), "R2 把字符串里的分号误判成多条声明"
    # 注意：R2 有意禁止「单行内联规则」（`{` 与 `}` 同行），
    # 所以 `.a { content: "x;y"; }` 仍会被拦下——这是设计，不是误报。
    assert find_compressed_css('.a { content: "x;y"; }')

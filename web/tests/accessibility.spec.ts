/**
 * 可访问性守门测试（P1-5-3）。
 *
 * 设计文档章节：不属于设计文档——`focus-visible`/`prefers-reduced-motion`/CI 前端测试
 * 是 2026-09-15 的 P1-5-3，属工程质量补充（设计文档 §13.4/§13.5 只规定 Web 的功能
 * 范围与技术栈）。
 *
 * 这里守的是两类"没有组件测试就没人知道"的东西：
 *
 * 1. **真实样式表 `src/styles.css`**：焦点可见（`:focus-visible`）与减少动态效果
 *    （`prefers-reduced-motion`）只存在于 CSS 里，组件测试看不到。用 postcss 解析
 *    **真实文件**并断言规则仍然存在——P1-5-1 把这份样式表从 59 行展开到 1000+ 行，
 *    删掉一条规则不会有任何构建错误，也没有别的测试会发现；
 * 2. **工作流里必须有前端测试步骤**：`.github/workflows/ci.yml` 此前只跑
 *    `npm run build`，`npm run test` 不加进去的话，P1-5-3 引入的测试永远不会执行
 *    （P1-4-5 的教训：CI 从挂上那天起一直是红的，只是没人看）。
 *
 * 最后一组 `测试自身的反证` 把这些规则指向合成样例：缺 `:focus-visible`、减动效果
 * 写在媒体查询之外时它们必须失败，否则"守门"只是永远通过的空转。
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

import postcss, { type AtRule, type Rule, type Root } from 'postcss'
import { describe, expect, it } from 'vitest'

/**
 * 用 `process.cwd()` 定位而不是 `import.meta.url`：vitest 会把 `import.meta.url`
 * 改写成 http 形式，`fileURLToPath` 会直接抛 "The URL must be of scheme file"。
 * 测试的 cwd 固定是 `web/`（`npm run test` 在 `web/` 下执行）。
 */
const webRoot = process.cwd()
const stylesPath = resolve(webRoot, 'src/styles.css')
const packageJsonPath = resolve(webRoot, 'package.json')
const workflowPath = resolve(dirname(webRoot), '.github/workflows/ci.yml')

const stylesCss = readFileSync(stylesPath, 'utf8')
const workflowYml = readFileSync(workflowPath, 'utf8')

interface RuleCheck {
  /** 选择器必须同时包含这些子串。 */
  selector: string[]
  /** 某条声明的 `prop: value` 片段（空白会被归一化）。 */
  declaration: string
  note: string
}

/** 只保留"直接写在样式表顶层或普通 at-rule 里"的规则，不含 `@media` 内的。 */
function topLevelRules(css: Root): Rule[] {
  const rules: Rule[] = []
  css.walkRules((rule) => {
    const ancestors: string[] = []
    let parent = rule.parent
    while (parent && parent.type !== 'root') {
      if (parent.type === 'atrule') ancestors.push(`@${(parent as AtRule).name}`)
      parent = parent.parent
    }
    if (!ancestors.includes('@media')) rules.push(rule)
  })
  return rules
}

function reducedMotionRules(css: Root): Rule[] {
  const rules: Rule[] = []
  css.walkAtRules('media', (atRule) => {
    if (!atRule.params.includes('prefers-reduced-motion')) return
    atRule.walkRules((rule) => rules.push(rule))
  })
  return rules
}

function selectorsContaining(css: Root, needle: string): string[] {
  const found: string[] = []
  css.walkRules((rule) => {
    if (rule.selector.includes(needle)) found.push(rule.selector)
  })
  return found
}

/** 断言：存在一条选择器匹配、且带指定声明的规则。 */
function expectRule(css: Root, check: RuleCheck): void {
  const matched = [...reducedMotionRules(css), ...topLevelRules(css)].filter((rule) =>
    check.selector.every((part) => rule.selector.includes(part)),
  )
  const selectors = matched.map((rule) => rule.selector)
  expect(
    selectors,
    `${check.note}：没有找到选择器同时含 ${check.selector.join(' + ')} 的规则`,
  ).not.toHaveLength(0)

  const declarations = matched.flatMap((rule) =>
    rule.nodes
      .filter((node) => node.type === 'decl')
      .map((declaration) => declaration.toString().replace(/\s+/g, ' ')),
  )
  expect(
    declarations.some((declaration) => declaration.includes(check.declaration)),
    `${check.note}：找到规则但缺少声明 ${check.declaration}`,
  ).toBe(true)
}

/** "无条件生效的 animation-duration"：写在了 `@media (prefers-reduced-motion)` 之外。 */
function hasUnconditionalAnimationDuration(css: Root): boolean {
  let found = false
  css.walkRules((rule) => {
    // 祖先里有 prefers-reduced-motion 媒体查询的规则才是"有条件的"；写在
    // 响应式断点里的 animation-duration 依旧是无条件生效的（不该被放过）。
    let conditional = false
    let parent = rule.parent
    while (parent && parent.type !== 'root') {
      if (parent.type === 'atrule') {
        const atRule = parent as AtRule
        if (atRule.name === 'media' && atRule.params.includes('prefers-reduced-motion')) {
          conditional = true
        }
      }
      parent = parent.parent
    }
    if (conditional) return
    rule.walkDecls('animation-duration', () => {
      found = true
    })
  })
  return found
}

/**
 * 找出"完全没有出现在任何焦点规则里"的可聚焦控件类型（选择器层面的粗检查）。
 *
 * 全局规则（选择器里没有任何元素名，例如 `:focus-visible { … }`）覆盖所有元素，
 * 此时直接通过；否则要求每种控件都至少有一条含它的焦点规则——只给 `input` 加焦点环
 * 而漏掉按钮，正是 P1-5-3 之前的真实状态。
 */
function focusableControlsMissingFrom(css: Root): string[] {
  const focusSelectors = selectorsContaining(css, ':focus')
  const globalFocus = focusSelectors.some((selector) =>
    selector
      .split(',')
      .map((part) => part.trim())
      .some((part) => /^:{1,2}[a-z-]+$/.test(part) || part === '*'),
  )
  if (globalFocus) return []
  const text = focusSelectors.join(' | ')
  return ['button', 'input', 'textarea', 'select'].filter((control) => !text.includes(control))
}

describe('styles.css 的可访问性层', () => {
  it('键盘焦点可见：`:focus-visible` 带真实可见的 outline', () => {
    expectRule(postcss.parse(stylesCss), {
      selector: [':focus-visible'],
      declaration: 'outline: 2px solid #b7ff5f',
      note: '键盘焦点环',
    })
  })

  it('每个可聚焦控件类型都落在焦点规则里', () => {
    expect(focusableControlsMissingFrom(postcss.parse(stylesCss))).toEqual([])
  })

  it('粗检查抓得到"只给 input 加了焦点环"的写法，也会认可全局规则', () => {
    const inputOnly = postcss.parse('input:focus { border-color: #b7ff5f; }')
    expect(focusableControlsMissingFrom(inputOnly)).toEqual(['button', 'textarea', 'select'])

    const globalRule = postcss.parse(':focus-visible { outline: 2px solid #b7ff5f; }')
    expect(focusableControlsMissingFrom(globalRule)).toEqual([])
  })

  it('尊重 prefers-reduced-motion：动画与过渡都被压掉', () => {
    const css = postcss.parse(stylesCss)
    expectRule(css, {
      selector: ['*'],
      declaration: 'animation-duration: .01ms !important',
      note: '减少动态效果（动画）',
    })
    expectRule(css, {
      selector: ['*'],
      declaration: 'transition-duration: .01ms !important',
      note: '减少动态效果（过渡）',
    })
  })

  it('减少动态效果必须写在 `@media (prefers-reduced-motion: reduce)` 里，不能无条件生效', () => {
    const css = postcss.parse(stylesCss)
    const blocks: string[] = []
    css.walkAtRules('media', (atRule) => {
      if (atRule.params.includes('prefers-reduced-motion')) blocks.push(atRule.params)
    })
    expect(blocks.length).toBeGreaterThan(0)
    expect(hasUnconditionalAnimationDuration(css), '减动样式出现在了媒体查询之外').toBe(false)
  })

  it('`.sr-only` 是"视觉隐藏但仍可访问"，不是 `display: none`', () => {
    const css = postcss.parse(stylesCss)
    const rule = [...reducedMotionRules(css), ...topLevelRules(css)].find((candidate) =>
      candidate.selector.includes('.sr-only'),
    )
    expect(rule, '找不到 .sr-only 规则').toBeDefined()
    const text = rule?.nodes
      .filter((node) => node.type === 'decl')
      .map((declaration) => declaration.toString().replace(/\s+/g, ' '))
      .join('\n') as string
    expect(text).toContain('position: absolute')
    expect(text).toContain('clip-path: inset(50%)')
    expect(text).not.toContain('display: none')
    expect(text).not.toContain('visibility: hidden')
  })
})

describe('CI 真的会跑前端测试', () => {
  it('前端 job 里存在 `npm run test` 步骤（否则这批测试永远不会执行）', () => {
    expect(workflowYml).toContain('npm run test')
  })

  it('package.json 定义了 `test` 脚本，且指向 vitest', () => {
    const packageJson = JSON.parse(readFileSync(packageJsonPath, 'utf8')) as {
      scripts: Record<string, string>
    }
    // 精确匹配 `vitest run`：写成 `vitest`（watch 模式）在 CI 里会挂住不返回。
    expect(packageJson.scripts.test).toBe('vitest run')
  })
})

describe('测试自身的反证：规则抓得到真实的缺失', () => {
  const reducedMotionBlock = [
    '@media (prefers-reduced-motion: reduce) {',
    '  *,',
    '  *::before {',
    '    animation-duration: .01ms !important;',
    '    transition-duration: .01ms !important;',
    '  }',
    '}',
  ].join('\n')

  it('缺少 `:focus-visible` 时焦点规则检查会失败', () => {
    expect(() =>
      expectRule(postcss.parse('.a { color: red; }'), {
        selector: [':focus-visible'],
        declaration: 'outline: 2px solid #b7ff5f',
        note: '键盘焦点环',
      }),
    ).toThrow()
  })

  it('焦点环写在规则里但没有 outline 值（只剩颜色变化）也会失败', () => {
    expect(() =>
      expectRule(postcss.parse(':focus-visible { color: #b7ff5f; }'), {
        selector: [':focus-visible'],
        declaration: 'outline: 2px solid #b7ff5f',
        note: '键盘焦点环',
      }),
    ).toThrow()
  })

  it('减动效果写在媒体查询之外时会被判定为无条件生效', () => {
    expect(hasUnconditionalAnimationDuration(postcss.parse('* { animation-duration: .01ms; }'))).toBe(
      true,
    )
    expect(hasUnconditionalAnimationDuration(postcss.parse(reducedMotionBlock))).toBe(false)
  })

  it('合成样例的减动块能通过同一套规则（不误报）', () => {
    const css = postcss.parse(reducedMotionBlock)
    expectRule(css, {
      selector: ['*'],
      declaration: 'animation-duration: .01ms !important',
      note: '减少动态效果（动画）',
    })
    expect(reducedMotionRules(css)).toHaveLength(1)
  })
})

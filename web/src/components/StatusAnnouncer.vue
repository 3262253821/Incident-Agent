<script setup lang="ts">
/**
 * 屏幕阅读器播报区（P1-5-3）。
 *
 * 为什么不是把 `aria-live` 直接挂在状态标签上：`aria-live` 只在**区域已经存在于
 * DOM 里之后**发生的变化才会被播报，而分析状态是从"READY"变成"ANALYZING"的；
 * 更关键的是加载态里的 `.spin` 图标是纯装饰，状态变化对读屏用户完全没有信号。
 * 所以这里固定渲染一个视口外的 live region（`role="status"` 蕴含
 * `aria-live="polite"`），文字由父组件驱动——它始终在 DOM 里，变化必被播报。
 */
defineProps<{ message: string }>()
</script>

<template>
  <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ message }}</p>
</template>

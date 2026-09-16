<script setup lang="ts">
/**
 * Incident Agent 的品牌标记（自研 SVG，不依赖任何图片文件）。
 *
 * 图形语义：**盾牌 + 告警脉冲**——盾取"故障诊断 / 把问题关在里面"，
 * 中间的脉冲折线取"信号 / 现场日志"。两者叠在一起刚好是这个项目在做的事：
 * 从现场信号里识别故障。用 `currentColor` 描边，所以跟随外层文字颜色
 * （侧栏与欢迎页都把它染成品牌蓝）。
 */
withDefaults(defineProps<{ size?: number }>(), { size: 26 })
</script>

<template>
  <svg
    class="brand-mark-svg"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    role="img"
    aria-label="Incident Agent"
    focusable="false"
  >
    <path
      d="M12 2.6 L20 5.6 V11.2 C20 16.1 16.6 19.8 12 21.4 C7.4 19.8 4 16.1 4 11.2 V5.6 Z"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linejoin="round"
    />
    <path
      d="M6.6 11.6 H9.2 L10.7 8.5 L13 14.7 L14.6 11.6 H17.4"
      stroke="currentColor"
      stroke-width="1.9"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

<style scoped>
.brand-mark-svg {
  display: block;
}
</style>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  steps: {
    type: Array,
    default: () => [],
  },
  toolsUsed: {
    type: Array,
    default: () => [],
  },
})

function parseStep(step) {
  if (typeof step !== 'string') {
    return { kind: 'other', title: '步骤', body: String(step) }
  }

  if (step.startsWith('📋 计划\n')) {
    return { kind: 'plan', title: '分析计划', body: step.slice('📋 计划\n'.length) }
  }
  if (step.startsWith('💭 推理\n')) {
    return { kind: 'reason', title: '推理', body: step.slice('💭 推理\n'.length) }
  }
  if (step.startsWith('🔧 ')) {
    const newline = step.indexOf('\n')
    const title = newline >= 0 ? step.slice(2, newline) : step.slice(2)
    const body = newline >= 0 ? step.slice(newline + 1) : ''
    return { kind: 'tool', title: `工具 · ${title}`, body }
  }
  if (step.startsWith('调用 ')) {
    const colon = step.indexOf(': ')
    if (colon >= 0) {
      return {
        kind: 'tool',
        title: `工具 · ${step.slice(3, colon)}`,
        body: step.slice(colon + 2),
      }
    }
  }

  return { kind: 'other', title: '步骤', body: step }
}

const parsedSteps = computed(() => props.steps.map(parseStep))

const summaryText = computed(() => {
  const toolCount = props.toolsUsed.length
  const stepCount = props.steps.length
  if (!stepCount) return '查看 Agent 执行过程'
  if (toolCount) return `Agent 执行了 ${stepCount} 步 · 调用 ${toolCount} 个工具`
  return `Agent 执行了 ${stepCount} 步`
})
</script>

<template>
  <details class="agent-steps">
    <summary>{{ summaryText }}</summary>
    <ol class="agent-steps-list">
      <li
        v-for="(step, index) in parsedSteps"
        :key="index"
        class="agent-step"
        :class="`agent-step--${step.kind}`"
      >
        <div class="agent-step-title">{{ step.title }}</div>
        <pre v-if="step.body" class="agent-step-body">{{ step.body }}</pre>
      </li>
    </ol>
  </details>
</template>

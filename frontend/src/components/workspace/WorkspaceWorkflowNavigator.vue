<script setup lang="ts">
type WorkflowStep = 1 | 2 | 3 | 4

const props = defineProps<{
  activeStep: WorkflowStep
  availableSteps: readonly WorkflowStep[]
  completedSteps: readonly WorkflowStep[]
}>()

const emit = defineEmits<{
  'select-step': [step: WorkflowStep]
}>()

const steps = [
  { id: 1, label: '研究区' },
  { id: 2, label: '缓冲区' },
  { id: 3, label: '分析' },
  { id: 4, label: '结果' },
] as const

function stateFor(step: WorkflowStep) {
  if (step === props.activeStep) return 'active'
  if (!props.availableSteps.includes(step)) return 'unavailable'
  if (props.completedSteps.includes(step)) return 'complete'
  return 'pending'
}

function selectStep(step: WorkflowStep) {
  if (!props.availableSteps.includes(step)) return
  emit('select-step', step)
}
</script>

<template>
  <nav class="workspace-workflow" aria-label="分析流程">
    <ol>
      <li
        v-for="step in steps"
        :key="step.id"
        :class="`is-${stateFor(step.id)}`"
        :data-state="stateFor(step.id)"
        :aria-current="step.id === activeStep ? 'step' : undefined"
      >
        <button
          type="button"
          class="step-button"
          :disabled="!availableSteps.includes(step.id)"
          @click="selectStep(step.id)"
        >
          <span class="step-status">
            <span v-if="stateFor(step.id) === 'complete'" aria-hidden="true">✓</span>
            <span v-else>{{ step.id }}</span>
          </span>
          <span class="step-label">{{ step.label }}</span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.workspace-workflow {
  flex: none;
  min-height: 36px;
  display: flex;
  align-items: center;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.workspace-workflow ol {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
  padding: 0;
  list-style: none;
}

.workspace-workflow li {
  min-width: 0;
  height: 36px;
  border-right: 1px solid var(--border);
  background: #fff;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
}

.step-button {
  height: 100%;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 14px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.step-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.step-button:focus-visible {
  border-radius: 0;
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

.step-status {
  flex: none;
  font-size: 12px;
  font-weight: 700;
}

.workspace-workflow li.is-active {
  background: var(--primary);
  color: #fff;
}

.workspace-workflow li.is-complete {
  background: #eceeed;
  color: #465159;
}

.step-label {
  white-space: nowrap;
}

.workspace-workflow li.is-unavailable {
  background: #f7f7f5;
  color: #92979a;
}

@media (max-width: 1180px) {
  .workspace-workflow {
    padding-inline: 0;
  }

  .workspace-workflow li {
    font-size: 12px;
  }
}
</style>

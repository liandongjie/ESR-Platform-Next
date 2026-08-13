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
          <span class="step-marker">
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
  min-height: 52px;
  display: flex;
  align-items: center;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 6px 20px rgba(43, 73, 121, 0.05);
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
  position: relative;
  min-width: 0;
  color: #7b879f;
  font-size: 13px;
  font-weight: 600;
}

.step-button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0;
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
  border-radius: 8px;
  outline: 2px solid var(--primary);
  outline-offset: 3px;
}

.workspace-workflow li:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 50%;
  left: calc(50% + 42px);
  right: calc(-50% + 42px);
  height: 1px;
  background: var(--border);
  transform: translateY(-50%);
}

.workspace-workflow li.is-complete:not(:last-child)::after {
  background: #a9c5ff;
}

.step-marker {
  position: relative;
  z-index: 1;
  flex: none;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid #dce3ee;
  border-radius: 50%;
  background: #f7f9fc;
  color: #7b879f;
  font-size: 11px;
  font-weight: 700;
}

.workspace-workflow li.is-active {
  color: var(--text);
}

.is-active .step-marker {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
  box-shadow: 0 0 0 4px rgba(51, 112, 255, 0.1);
}

.workspace-workflow li.is-complete {
  color: #496a9f;
}

.is-complete .step-marker {
  border-color: #b8cffd;
  background: var(--primary-soft);
  color: var(--primary);
}

.step-label {
  position: relative;
  z-index: 1;
  padding: 2px 6px;
  background: var(--surface);
  white-space: nowrap;
}

@media (max-width: 1180px) {
  .workspace-workflow {
    padding-inline: 8px;
  }

  .workspace-workflow li {
    gap: 5px;
    font-size: 12px;
  }

  .workspace-workflow li:not(:last-child)::after {
    left: calc(50% + 34px);
    right: calc(-50% + 34px);
  }

  .step-label {
    padding-inline: 3px;
  }
}
</style>

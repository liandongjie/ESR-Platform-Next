<script setup lang="ts">
type DrawingMode = 'point' | 'polyline' | 'rectangle' | 'polygon'

defineProps<{
  disabled: boolean
  activeDrawingMode: DrawingMode | null
  drawingError: string | null
}>()

defineEmits<{
  'start-drawing': [mode: DrawingMode]
  'cancel-drawing': []
}>()

const drawingModes: Array<{ mode: DrawingMode; label: string }> = [
  { mode: 'point', label: '点' },
  { mode: 'polyline', label: '线' },
  { mode: 'rectangle', label: '矩形' },
  { mode: 'polygon', label: '多边形' },
]
</script>

<template>
  <div class="study-area-draw-input">
    <div class="study-area-input-heading">
      <strong>在线绘制</strong>
      <el-tag v-if="activeDrawingMode" type="primary" effect="plain" size="small">
        {{ drawingModes.find((item) => item.mode === activeDrawingMode)?.label }}绘制中
      </el-tag>
    </div>
    <div class="drawing-tool-grid">
      <el-button
        v-for="item in drawingModes"
        :key="item.mode"
        :type="activeDrawingMode === item.mode ? 'primary' : 'default'"
        :disabled="disabled"
        :aria-label="`绘制${item.label}`"
        @click="$emit('start-drawing', item.mode)"
      >
        {{ item.label }}
      </el-button>
    </div>
    <el-button
      :disabled="disabled || !activeDrawingMode"
      @click="$emit('cancel-drawing')"
    >
      取消绘制
    </el-button>
    <el-alert
      v-if="drawingError"
      :title="drawingError"
      type="error"
      :closable="false"
      show-icon
    />
  </div>
</template>

<style scoped>
.study-area-draw-input {
  display: grid;
  gap: 10px;
}

.study-area-input-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.study-area-input-heading > strong {
  font-size: 13px;
}

.drawing-tool-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.drawing-tool-grid :deep(.el-button) {
  margin-left: 0;
}
</style>

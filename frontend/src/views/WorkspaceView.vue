<script setup lang="ts">
import { computed, onMounted } from 'vue'

import StatusCard from '@/components/common/StatusCard.vue'
import MapCanvas from '@/components/map/MapCanvas.vue'
import { useSystemStore } from '@/stores/system'

const systemStore = useSystemStore()

const backendText = computed(() => {
  if (systemStore.loading) return '检查中'
  return systemStore.backendOnline ? '在线' : '未连接'
})

onMounted(() => {
  void systemStore.load()
})
</script>

<template>
  <div class="workspace-page">
    <section class="page-heading">
      <div>
        <p class="eyebrow">ANALYSIS WORKSPACE</p>
        <h1>环境社会风险分析工作台</h1>
        <p>当前先建立可靠的工程边界，再接入地图绘制、POI 与真实栅格计算。</p>
      </div>
      <el-button type="primary" :loading="systemStore.loading" @click="systemStore.load">
        检查服务
      </el-button>
    </section>

    <section class="status-grid">
      <StatusCard label="后端服务" :value="backendText" hint="Flask / API v1" />
      <StatusCard label="内部坐标系" value="EPSG:4326" hint="地图展示适配 GCJ-02" />
      <StatusCard label="结果保留" value="24 小时" hint="后续由清理任务执行" />
      <StatusCard label="项目阶段" value="工程骨架" hint="尚未接入真实分析" />
    </section>

    <section class="workspace-grid">
      <aside class="workflow-panel panel-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">WORKFLOW</p>
            <h2>分析流程</h2>
          </div>
        </div>

        <ol class="workflow-list">
          <li class="active">
            <span>01</span>
            <div>
              <strong>选择研究区</strong>
              <small>地图绘制 / 预置风险点</small>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>设置缓冲区</strong>
              <small>100～5000 米，后端再次校验</small>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>配置风险指标</strong>
              <small>12 项标准化指标与权重</small>
            </div>
          </li>
          <li>
            <span>04</span>
            <div>
              <strong>提交异步任务</strong>
              <small>Celery 队列受控执行</small>
            </div>
          </li>
          <li>
            <span>05</span>
            <div>
              <strong>查看与导出结果</strong>
              <small>地图、统计、GeoTIFF、ZIP</small>
            </div>
          </li>
        </ol>
      </aside>

      <MapCanvas />

      <aside class="result-panel panel-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">CURRENT SELECTION</p>
            <h2>当前分析</h2>
          </div>
        </div>

        <el-empty description="尚未选择研究区" :image-size="90" />
        <el-alert
          title="骨架阶段不会使用模拟风险值冒充真实结果"
          type="info"
          :closable="false"
          show-icon
        />
      </aside>
    </section>

    <el-alert
      v-if="systemStore.error"
      class="service-error"
      :title="`后端连接失败：${systemStore.error}`"
      type="warning"
      :closable="false"
      show-icon
    />
  </div>
</template>

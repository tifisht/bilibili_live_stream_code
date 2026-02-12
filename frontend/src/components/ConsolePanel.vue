<script setup>
import { ref, watch, nextTick, onMounted } from 'vue';
import { useBridge } from '@/api/bridge';

defineProps(['liveState']);
const { state, getAppConfig, setAppConfig } = useBridge();

const logsContainer = ref(null);
const isWin32 = ref(false);
const hasTray = ref(false);
const minToTray = ref(true);

onMounted(async () => {
  try {
    const config = await getAppConfig();
    if (config) {
      isWin32.value = config.is_win32;
      hasTray.value = config.has_tray || config.is_win32;
      minToTray.value = config.min_to_tray;
    }
  } catch (e) {
    console.error("Failed to load app config:", e);
  }
});

const updateTrayConfig = async () => {
  await setAppConfig('min_to_tray', minToTray.value);
};

watch(() => state.logs.length, () => {
  nextTick(() => {
    if (logsContainer.value) {
      logsContainer.value.scrollTop = logsContainer.value.scrollHeight;
    }
  });
});
</script>

<template>
  <div class="panel fade-in">
    <div class="panel-header">
      <h2>控制台</h2>
      <div v-if="hasTray" class="tray-toggle">
        <span class="label-text">关闭时最小化到托盘</span>
        <label class="switch">
          <input type="checkbox" v-model="minToTray" @change="updateTrayConfig">
          <span class="slider"></span>
        </label>
      </div>
    </div>

    <div class="logs" ref="logsContainer">
      <div v-if="state.logs.length === 0" style="padding: 10px; color: #666;">暂无日志...</div>
      <div v-for="(l,i) in state.logs" :key="i" class="log-item">{{ l }}</div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  height: 100%; /* Fix layout collapse */
}

/* Restore original header look but keep flex for toggle */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px; /* Original spacing */
  flex-shrink: 0;
}

.panel-header h2 {
  margin: 0;
  font-size: 1.5em; /* Default h2 size */
}

.tray-toggle {
  display: flex;
  align-items: center;
  font-size: 13px;
  color: var(--text-sub);
  gap: 10px;
}

/* Switch Styles */
.switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #ccc;
  transition: .4s;
  border-radius: 20px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  transition: .4s;
  border-radius: 50%;
}

input:checked + .slider {
  background-color: var(--primary-color);
}

input:checked + .slider:before {
  transform: translateX(16px);
}

.logs {
  background: #1E1E1E; color: #81C995;
  padding: 15px; border-radius: 12px;
  flex: 1; /* Fill remaining space */
  overflow-y: auto;
  font-family: monospace; font-size: 12px;
  box-shadow: inset 0 2px 8px rgba(0,0,0,0.2);
  min-height: 0;
}

.log-item {
  margin-bottom: 4px;
  line-height: 1.4;
  border-left: 2px solid transparent;
  padding-left: 8px;
  word-break: break-all;
}
.log-item:hover {
  background: rgba(255,255,255,0.05);
  border-left-color: #81C995;
}
</style>

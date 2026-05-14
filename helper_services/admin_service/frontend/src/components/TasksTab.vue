<template>
  <div class="tab-content">
    <div class="toolbar">
      <h2>Задачи индексации</h2>
      <button class="btn btn-ghost" @click="load">↻</button>
    </div>

    <div class="card">
      <div v-if="loading && !tasks.length" class="loading">Загрузка…</div>
      <table v-else-if="tasks.length">
        <thead>
          <tr>
            <th>Файл</th>
            <th>Статус</th>
            <th>+ Чанков</th>
            <th>− Старых</th>
            <th>Создана</th>
            <th>Завершена</th>
            <th>Ошибка</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id">
            <td>{{ t.filename }}</td>
            <td>
              <span :class="['badge', `badge-${t.status}`]">{{ statusLabel(t.status) }}</span>
            </td>
            <td class="dim">{{ t.chunks_added || '—' }}</td>
            <td class="dim">{{ t.chunks_deleted || '—' }}</td>
            <td class="dim">{{ formatDate(t.created_at) }}</td>
            <td class="dim">{{ formatDate(t.finished_at) }}</td>
            <td class="err-cell">{{ t.error || '' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">
        Задач нет. Запустите индексацию из вкладки <b>Файлы</b>.
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { tasksApi } from '../api.js'

const tasks   = ref([])
const loading = ref(false)
let timer = null

async function load() {
  loading.value = true
  try { tasks.value = await tasksApi.list() } catch {}
  finally { loading.value = false }

  const hasActive = tasks.value.some(t => t.status === 'running' || t.status === 'pending')
  if (hasActive && !timer) {
    timer = setInterval(load, 3000)
  } else if (!hasActive && timer) {
    clearInterval(timer)
    timer = null
  }
}

const STATUS_LABELS = { pending: 'ожидание', running: 'выполняется', done: 'готово', error: 'ошибка' }
function statusLabel(s) { return STATUS_LABELS[s] || s }

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

onMounted(load)
onUnmounted(() => { if (timer) { clearInterval(timer); timer = null } })
</script>

<template>
  <div class="tab-content">
    <div class="toolbar">
      <h2>Система</h2>
    </div>

    <!-- Сессии телефонии -->
    <div class="section-card card">
      <div class="section-header">
        <div>
          <div class="section-title">История звонков (телефония)</div>
          <div class="section-desc">
            JSON-файлы с историей диалогов по каждому номеру телефона.
            Хранятся в volume <code>telephony_sessions</code>.
          </div>
        </div>
        <div class="section-meta dim">
          Файлов: <strong>{{ sessionCount ?? '…' }}</strong>
        </div>
      </div>
      <div class="section-body">
        <div v-if="sessionsStatus === 'ok'" class="alert alert-success">
          ✓ Удалено {{ deletedCount }} файлов сессий.
        </div>
        <div v-if="sessionsStatus === 'error'" class="alert alert-error">{{ sessionsError }}</div>
        <button
          class="btn btn-danger"
          :disabled="sessionsStatus === 'loading' || sessionCount === 0"
          @click="clearSessions"
        >
          {{ sessionsStatus === 'loading' ? 'Очистка…' : 'Очистить историю звонков' }}
        </button>
      </div>
    </div>

    <!-- Голосовой чат -->
    <div class="section-card card">
      <div class="section-header">
        <div>
          <div class="section-title">История голосового чата (браузер)</div>
          <div class="section-desc">
            Хранится только в памяти браузера на время сессии.
            Каждое новое подключение начинает диалог заново — очистка на сервере не требуется.
          </div>
        </div>
      </div>
    </div>

    <!-- ChromaDB -->
    <div class="section-card card">
      <div class="section-header">
        <div>
          <div class="section-title">База знаний ИИ (ChromaDB)</div>
          <div class="section-desc">
            Принудительно перезагружает коллекцию в ai_service — актуально после ручных правок чанков.
          </div>
        </div>
      </div>
      <div class="section-body">
        <div v-if="reloadStatus === 'ok'" class="alert alert-success">✓ База знаний обновлена.</div>
        <div v-if="reloadStatus === 'error'" class="alert alert-error">{{ reloadError }}</div>
        <button
          class="btn btn-warning"
          :disabled="reloadStatus === 'loading'"
          @click="reloadDb"
        >
          {{ reloadStatus === 'loading' ? 'Обновление…' : '⟳ Реиндексировать ChromaDB' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { systemApi, aiApi } from '../api.js'

const sessionCount  = ref(null)
const deletedCount  = ref(0)
const sessionsStatus = ref('idle')
const sessionsError  = ref('')

const reloadStatus = ref('idle')
const reloadError  = ref('')

async function loadStats() {
  try {
    const data = await systemApi.sessionsStats()
    sessionCount.value = data.count
  } catch {
    sessionCount.value = null
  }
}

async function clearSessions() {
  if (!confirm(`Удалить ${sessionCount.value} файлов истории звонков?`)) return
  sessionsStatus.value = 'loading'
  sessionsError.value = ''
  try {
    const data = await systemApi.clearSessions()
    deletedCount.value = data.deleted
    sessionsStatus.value = 'ok'
    sessionCount.value = 0
    setTimeout(() => { sessionsStatus.value = 'idle' }, 4000)
  } catch (e) {
    sessionsError.value = typeof e === 'string' ? e : 'Ошибка очистки сессий'
    sessionsStatus.value = 'error'
  }
}

async function reloadDb() {
  reloadStatus.value = 'loading'
  reloadError.value = ''
  try {
    await aiApi.reloadDb()
    reloadStatus.value = 'ok'
    setTimeout(() => { reloadStatus.value = 'idle' }, 3000)
  } catch (e) {
    reloadError.value = typeof e === 'string' ? e : 'Ошибка реиндексации'
    reloadStatus.value = 'error'
  }
}

onMounted(loadStats)
</script>

<style scoped>
.section-card { margin-bottom: 0; }
.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 18px 22px 14px;
  gap: 16px;
}
.section-title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.section-desc  { font-size: 13px; color: #6b7280; }
.section-desc code { background: #f3f4f6; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.section-body  { padding: 0 22px 18px; display: flex; flex-direction: column; gap: 10px; }
.section-meta  { white-space: nowrap; padding-top: 2px; font-size: 13px; }
</style>

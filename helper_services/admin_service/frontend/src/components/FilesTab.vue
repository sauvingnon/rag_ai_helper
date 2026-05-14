<template>
  <div class="tab-content">
    <div class="toolbar">
      <h2>Файлы</h2>
      <div class="toolbar-actions">
        <label class="btn btn-primary">
          + Загрузить
          <input
            type="file"
            hidden
            accept=".yaml,.yml,.txt,.pdf,.docx"
            @change="onUpload"
          />
        </label>
        <button class="btn btn-ghost" @click="load">↻</button>
      </div>
    </div>

    <div v-if="error" class="alert alert-error">{{ error }}</div>

    <div class="card">
      <div v-if="loading" class="loading">Загрузка…</div>
      <template v-else-if="files.length">
        <table>
          <thead>
            <tr>
              <th>Файл</th>
              <th>Размер</th>
              <th>Загружен</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in files" :key="f.file_id">
              <td>{{ f.filename }}</td>
              <td class="dim">{{ formatSize(f.size_bytes) }}</td>
              <td class="dim">{{ formatDate(f.uploaded_at) }}</td>
              <td class="actions">
                <button class="btn btn-sm btn-ghost" title="Скачать" @click="download(f)">↓</button>
                <button
                  class="btn btn-sm btn-success"
                  :disabled="indexing[f.file_id]"
                  title="Запустить индексацию"
                  @click="index(f)"
                >
                  {{ indexing[f.file_id] ? '…' : '▶ Индексировать' }}
                </button>
                <button class="btn btn-sm btn-danger" title="Удалить" @click="remove(f)">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
      <div v-else class="empty">Файлов нет. Загрузите первый файл.</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { filesApi } from '../api.js'

const files   = ref([])
const loading = ref(false)
const error   = ref('')
const indexing = ref({})

async function load() {
  loading.value = true
  error.value = ''
  try {
    files.value = await filesApi.list()
  } catch {
    error.value = 'Ошибка загрузки списка файлов'
  } finally {
    loading.value = false
  }
}

async function onUpload(e) {
  const file = e.target.files[0]
  if (!file) return
  e.target.value = ''
  error.value = ''
  try {
    await filesApi.upload(file)
    await load()
  } catch (msg) {
    error.value = typeof msg === 'string' ? msg : 'Ошибка загрузки файла'
  }
}

async function download(f) {
  try {
    await filesApi.download(f.file_id, f.filename)
  } catch {
    error.value = 'Ошибка скачивания'
  }
}

async function index(f) {
  indexing.value = { ...indexing.value, [f.file_id]: true }
  error.value = ''
  try {
    await filesApi.index(f.file_id)
  } catch (msg) {
    error.value = typeof msg === 'string' ? msg : 'Ошибка запуска индексации'
  } finally {
    indexing.value = { ...indexing.value, [f.file_id]: false }
  }
}

async function remove(f) {
  if (!confirm(`Удалить файл «${f.filename}»?`)) return
  error.value = ''
  try {
    await filesApi.delete(f.file_id)
    await load()
  } catch {
    error.value = 'Ошибка удаления файла'
  }
}

function formatSize(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / 1_048_576).toFixed(1)} МБ`
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

onMounted(load)
</script>

<template>
  <div class="tab-content">
    <div class="toolbar">
      <h2>Чанки</h2>
      <div class="toolbar-actions">
        <select v-model="filterFileId" @change="resetAndLoad">
          <option value="">Все файлы</option>
          <option v-for="f in files" :key="f.file_id" :value="f.file_id">
            {{ f.filename }}
          </option>
        </select>
        <button class="btn btn-ghost" @click="load">↻</button>
        <button
          class="btn btn-warning"
          :disabled="reloadStatus === 'loading'"
          @click="reloadAiDb"
        >
          {{ reloadStatus === 'loading' ? 'Обновление…' : '⟳ Реиндексировать БД' }}
        </button>
      </div>
    </div>

    <div v-if="needsReload && reloadStatus !== 'ok'" class="alert alert-warning">
      ⚠ Чанки изменены — база знаний ИИ устарела. Нажмите «Реиндексировать БД» чтобы применить изменения.
    </div>
    <div v-if="reloadStatus === 'ok'" class="alert alert-success">
      ✓ База знаний ИИ обновлена.
    </div>
    <div v-if="reloadStatus === 'error'" class="alert alert-error">Ошибка реиндексации — проверьте что ai_service запущен.</div>

    <div v-if="error" class="alert alert-error">{{ error }}</div>

    <div class="card">
      <div v-if="loading" class="loading">Загрузка…</div>
      <template v-else>
        <div class="meta-info">Найдено: {{ total }} чанков</div>
        <table v-if="items.length">
          <thead>
            <tr>
              <th style="width:200px">Название</th>
              <th style="width:90px">Тип</th>
              <th>Текст</th>
              <th style="width:140px">Источник</th>
              <th style="width:80px">Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in items" :key="c.id">
              <td>{{ c.name || '—' }}</td>
              <td><span class="badge">{{ c.type || 'general' }}</span></td>
              <td class="text-cell">{{ truncate(c.text || c.document) }}</td>
              <td class="dim">{{ c.source_filename || '—' }}</td>
              <td class="actions">
                <button class="btn btn-sm btn-ghost" title="Редактировать" @click="openEdit(c)">✏</button>
                <button class="btn btn-sm btn-danger" title="Удалить" @click="remove(c.id)">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">Чанков нет.</div>

        <div v-if="total > limit" class="pagination">
          <button class="btn btn-ghost btn-sm" :disabled="offset === 0" @click="prevPage">← Назад</button>
          <span>{{ currentPage }} / {{ totalPages }}</span>
          <button class="btn btn-ghost btn-sm" :disabled="offset + limit >= total" @click="nextPage">Вперёд →</button>
        </div>
      </template>
    </div>

    <!-- Edit modal -->
    <div v-if="editChunk" class="modal-overlay" @click.self="editChunk = null">
      <div class="modal">
        <div class="modal-header">
          <h3>Редактировать чанк</h3>
          <button class="close-btn" @click="editChunk = null">×</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label>Название</label>
            <input v-model="editForm.name" type="text" />
          </div>
          <div class="field">
            <label>Тип</label>
            <input v-model="editForm.type" type="text" placeholder="general" />
          </div>
          <div class="field">
            <label>Текст</label>
            <textarea v-model="editForm.text" rows="6"></textarea>
          </div>
          <div class="field">
            <label>Ключевые слова</label>
            <input v-model="editForm.keywords" type="text" />
          </div>
          <div class="field">
            <label>Примечания</label>
            <input v-model="editForm.notes" type="text" />
          </div>
          <div v-if="saveError" class="alert alert-error">{{ saveError }}</div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="editChunk = null">Отмена</button>
          <button class="btn btn-primary" :disabled="saving" @click="saveEdit">
            {{ saving ? 'Сохранение…' : 'Сохранить' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { chunksApi, filesApi, aiApi } from '../api.js'

const LIMIT = 50

const items       = ref([])
const files       = ref([])
const loading     = ref(false)
const error       = ref('')
const total       = ref(0)
const offset      = ref(0)
const limit       = LIMIT
const filterFileId = ref('')

const editChunk  = ref(null)
const editForm   = ref({})
const saving     = ref(false)
const saveError  = ref('')

const needsReload  = ref(false)
const reloadStatus = ref('idle') // 'idle' | 'loading' | 'ok' | 'error'

const currentPage = computed(() => Math.floor(offset.value / limit) + 1)
const totalPages  = computed(() => Math.ceil(total.value / limit))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await chunksApi.list({
      source_file_id: filterFileId.value || undefined,
      offset: offset.value,
      limit,
    })
    items.value = res.items
    total.value = res.total
  } catch {
    error.value = 'Ошибка загрузки чанков'
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  offset.value = 0
  load()
}

async function loadFiles() {
  try { files.value = await filesApi.list() } catch {}
}

function openEdit(c) {
  editChunk.value = c
  saveError.value = ''
  editForm.value = {
    name:     c.name     || '',
    type:     c.type     || 'general',
    text:     c.text     || '',
    keywords: c.keywords || '',
    notes:    c.notes    || '',
  }
}

async function saveEdit() {
  saving.value = true
  saveError.value = ''
  try {
    await chunksApi.update(editChunk.value.id, editForm.value)
    editChunk.value = null
    needsReload.value = true
    reloadStatus.value = 'idle'
    await load()
  } catch (msg) {
    saveError.value = typeof msg === 'string' ? msg : 'Ошибка сохранения'
  } finally {
    saving.value = false
  }
}

async function remove(id) {
  if (!confirm('Удалить чанк?')) return
  error.value = ''
  try {
    await chunksApi.delete(id)
    needsReload.value = true
    reloadStatus.value = 'idle'
    await load()
  } catch {
    error.value = 'Ошибка удаления чанка'
  }
}

async function reloadAiDb() {
  reloadStatus.value = 'loading'
  try {
    await aiApi.reloadDb()
    needsReload.value = false
    reloadStatus.value = 'ok'
    setTimeout(() => { reloadStatus.value = 'idle' }, 3000)
  } catch {
    reloadStatus.value = 'error'
  }
}

function prevPage() { offset.value = Math.max(0, offset.value - limit); load() }
function nextPage() { offset.value = offset.value + limit; load() }
function truncate(s) { if (!s) return '—'; return s.length > 130 ? s.slice(0, 130) + '…' : s }

onMounted(() => { load(); loadFiles() })
</script>

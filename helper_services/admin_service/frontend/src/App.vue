<template>
  <div class="app">
    <header>
      <span class="logo">RAG Admin</span>
      <nav>
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="['tab-btn', { active: currentTab === tab.key }]"
          @click="currentTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </nav>
    </header>
    <main>
      <FilesTab v-if="currentTab === 'files'" />
      <ChunksTab v-else-if="currentTab === 'chunks'" />
      <TasksTab v-else-if="currentTab === 'tasks'" />
      <SystemTab v-else-if="currentTab === 'system'" />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import FilesTab from './components/FilesTab.vue'
import ChunksTab from './components/ChunksTab.vue'
import TasksTab from './components/TasksTab.vue'
import SystemTab from './components/SystemTab.vue'

const tabs = [
  { key: 'files',  label: 'Файлы' },
  { key: 'chunks', label: 'Чанки' },
  { key: 'tasks',  label: 'Задачи' },
  { key: 'system', label: 'Система' },
]
const currentTab = ref('files')
</script>

<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; background: #f0f2f5; color: #1a1a2e; }

.app { min-height: 100vh; display: flex; flex-direction: column; }

header {
  background: #1a1a2e;
  color: white;
  padding: 0 28px;
  display: flex;
  align-items: center;
  gap: 36px;
  height: 56px;
  position: sticky;
  top: 0;
  z-index: 10;
}
.logo { font-size: 16px; font-weight: 700; letter-spacing: 1px; color: #60a5fa; }
nav { display: flex; gap: 2px; }
.tab-btn {
  background: none;
  border: none;
  color: rgba(255,255,255,.55);
  padding: 8px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all .15s;
}
.tab-btn:hover  { background: rgba(255,255,255,.08); color: white; }
.tab-btn.active { background: rgba(255,255,255,.14); color: white; }

main { padding: 28px; max-width: 1280px; margin: 0 auto; width: 100%; }

/* ── Shared layout ─────────────────────────────── */
.tab-content { display: flex; flex-direction: column; gap: 18px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; }
.toolbar h2 { font-size: 20px; font-weight: 600; }
.toolbar-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

/* ── Card ──────────────────────────────────────── */
.card {
  background: white;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,.07);
}

/* ── Table ─────────────────────────────────────── */
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 11px 16px; border-bottom: 1px solid #eff0f2; font-size: 14px; }
th { background: #f8f9fb; font-weight: 600; color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: .4px; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafbfc; }
.actions { display: flex; gap: 6px; white-space: nowrap; }
.loading, .empty { padding: 48px; text-align: center; color: #9ca3af; font-size: 14px; }
.meta-info { padding: 10px 16px; font-size: 13px; color: #9ca3af; border-bottom: 1px solid #eff0f2; }
.text-cell { color: #4b5563; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dim { font-size: 12px; color: #9ca3af; }
.err-cell { color: #dc2626; font-size: 12px; max-width: 220px; word-break: break-word; }
.pagination {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; justify-content: center;
  border-top: 1px solid #eff0f2; font-size: 13px; color: #6b7280;
}

/* ── Alert ─────────────────────────────────────── */
.alert { padding: 12px 16px; border-radius: 8px; font-size: 14px; }
.alert-error   { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.alert-warning { background: #fffbeb; color: #92400e; border: 1px solid #fcd34d; }
.alert-success { background: #f0fdf4; color: #166534; border: 1px solid #86efac; }

/* ── Buttons ───────────────────────────────────── */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 7px;
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: none; transition: all .15s; white-space: nowrap;
}
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn-primary   { background: #2563eb; color: white; }
.btn-primary:hover:not(:disabled)  { background: #1d4ed8; }
.btn-ghost     { background: white; color: #374151; border: 1px solid #d1d5db; }
.btn-ghost:hover:not(:disabled)    { background: #f9fafb; }
.btn-success   { background: #16a34a; color: white; }
.btn-success:hover:not(:disabled)  { background: #15803d; }
.btn-danger    { background: white; color: #dc2626; border: 1px solid #fca5a5; }
.btn-danger:hover:not(:disabled)   { background: #fff1f2; }
.btn-warning   { background: #d97706; color: white; }
.btn-warning:hover:not(:disabled)  { background: #b45309; }
.btn-sm        { padding: 5px 10px; font-size: 12px; }

/* ── Select ────────────────────────────────────── */
select {
  padding: 7px 10px;
  border: 1px solid #d1d5db;
  border-radius: 7px;
  font-size: 13px;
  background: white;
  cursor: pointer;
}

/* ── Badges ────────────────────────────────────── */
.badge {
  display: inline-block; padding: 2px 9px; border-radius: 12px;
  font-size: 11px; font-weight: 600; background: #e5e7eb; color: #374151;
}
.badge-done    { background: #dcfce7; color: #166534; }
.badge-running { background: #dbeafe; color: #1e40af; }
.badge-pending { background: #fef9c3; color: #854d0e; }
.badge-error   { background: #fee2e2; color: #991b1b; }

/* ── Modal ─────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal {
  background: white; border-radius: 12px;
  width: 520px; max-width: 95vw;
  box-shadow: 0 24px 64px rgba(0,0,0,.25);
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px; border-bottom: 1px solid #eff0f2;
}
.modal-header h3 { font-size: 16px; font-weight: 600; }
.close-btn { background: none; border: none; font-size: 20px; cursor: pointer; color: #9ca3af; line-height: 1; }
.close-btn:hover { color: #374151; }
.modal-body {
  padding: 20px 22px;
  display: flex; flex-direction: column; gap: 14px;
  max-height: 60vh; overflow-y: auto;
}
.field { display: flex; flex-direction: column; gap: 5px; }
.field label { font-size: 12px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: .4px; }
.field input, .field textarea {
  padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 7px;
  font-size: 14px; font-family: inherit; outline: none;
}
.field input:focus, .field textarea:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,.1); }
.field textarea { resize: vertical; min-height: 80px; }
.modal-footer {
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 16px 22px; border-top: 1px solid #eff0f2;
}
</style>

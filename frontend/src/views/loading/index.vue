<template>
  <section class="page" data-module="loading">
    <header class="page-head">
      <div>
        <h2>装卸作业管理</h2>
        <p class="page-desc">维护装卸记录，支持多选记录后逐条更新装卸类型、开门时长与运单状态，批量提交事务落库、断网可续传。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记装卸记录</button>
        <button class="btn" type="button" @click="exportRows">导出装卸作业清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>装卸状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <label class="select-all">
        <input type="checkbox" :checked="allSelected" :disabled="!rows.length" @change="toggleSelectAll" />
        全选本页
      </label>
      <span>已选 {{ selectedIds.length }} 条</span>
      <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="openBatch">
        批量更新装卸信息
      </button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check">选择</th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>明细 / 动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="col-check">
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              @change="toggleSelect(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <template v-if="column === '开门时长'">{{ row[column] ?? 0 }} 分钟</template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="viewDetail(row)">作业明细</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无装卸作业数据，可先登记装卸记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条装卸作业记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 批量更新弹层：每条选中记录独立编辑装卸类型、开门时长、运单状态 -->
    <div v-if="batchOpen" class="modal-mask" @click.self="closeBatch">
      <div class="modal">
        <div class="modal-head">
          <h3>批量更新装卸信息（{{ batchDrafts.length }} 条）</h3>
          <button class="link" type="button" @click="closeBatch">关闭</button>
        </div>
        <p class="modal-tip">
          逐条维护后一次提交：服务端按批次事务落库，任一项失败整批回滚；网络中断后点「继续提交」，
          只补写未完成项，已完成项不会重复写入。批次号：{{ batchId }}
        </p>
        <table class="data-table batch-table">
          <thead>
            <tr>
              <th>记录编号</th>
              <th>运单编号</th>
              <th>装卸类型</th>
              <th>开门时长（分钟）</th>
              <th>运单状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="draft in batchDrafts" :key="draft.id">
              <td>{{ draft['记录编号'] }}</td>
              <td>{{ draft['运单编号'] }}</td>
              <td>
                <select v-model="draft['装卸类型']">
                  <option value="" disabled>请选择</option>
                  <option v-for="t in options.loadingTypes" :key="t" :value="t">{{ t }}</option>
                </select>
              </td>
              <td>
                <input v-model.number="draft['开门时长']" type="number" min="0" step="1" />
              </td>
              <td>
                <select v-model="draft['运单状态']">
                  <option value="" disabled>请选择</option>
                  <option v-for="s in options.waybillStatuses" :key="s" :value="s">{{ s }}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="modal-foot">
          <span v-if="batchMessage" class="ok-text">{{ batchMessage }}</span>
          <span v-if="batchError" class="error-text">{{ batchError }}</span>
          <span v-else-if="!batchValid" class="muted-text">请把每条记录的装卸类型、开门时长、运单状态填写完整</span>
          <div class="modal-actions">
            <button class="btn ghost" type="button" @click="closeBatch">取消</button>
            <button class="btn primary" type="button" :disabled="!batchValid || batchSubmitting" @click="submitBatch">
              {{ batchSubmitting ? '提交中…' : (batchRetrying ? '继续提交（从未完成项）' : '批量提交') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 作业明细抽屉：装卸记录与关联运单详情同源展示 -->
    <div v-if="detailOpen" class="modal-mask" @click.self="closeDetail">
      <div class="drawer">
        <div class="modal-head">
          <h3>作业明细</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </div>
        <div v-if="detailLoading" class="muted-text">明细加载中…</div>
        <template v-else>
          <h4 class="detail-title">装卸记录</h4>
          <table class="data-table detail-table">
            <tbody>
              <tr v-for="column in columns" :key="column">
                <th>{{ column }}</th>
                <td>
                  <template v-if="column === '开门时长'">{{ detailEntry?.[column] ?? 0 }} 分钟</template>
                  <template v-else>{{ detailEntry?.[column] ?? '—' }}</template>
                </td>
              </tr>
            </tbody>
          </table>
          <h4 class="detail-title">关联运单</h4>
          <div v-if="detailWaybillError" class="error-text">{{ detailWaybillError }}</div>
          <table v-else-if="detailWaybill" class="data-table detail-table">
            <tbody>
              <tr v-for="field in waybillFields" :key="field">
                <th>{{ field }}</th>
                <td>{{ detailWaybill[field] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

interface BatchDraft {
  id: number
  记录编号: string
  运单编号: string
  装卸类型: string
  开门时长: number | string
  运单状态: string
}

interface UpdateOptions {
  loadingTypes: string[]
  waybillStatuses: string[]
}

interface BatchResponse {
  ok: boolean
  message: string
  batch_id: string
  updated: number[]
  skipped: number[]
  entries: Row[]
}

const ENDPOINT = '/api/loading'
const columns = ["记录编号", "运单编号", "装卸类型", "月台编号", "开门时长", "运单状态", "装卸人员", "开始时间", "装卸状态"]
const waybillFields = ["运单编号", "发货方", "收货方", "货物名称", "温层要求", "发运日期", "预计到达", "运单状态"]
const actions = ["开始装卸", "确认完成", "标记超时"]
const statuses = ["待装卸", "装卸中", "已完成", "已超时"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const selectedIds = ref<number[]>([])
const options = ref<UpdateOptions>({ loadingTypes: ["装车", "卸车"], waybillStatuses: [] })

const allSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))))

const stats = computed(() => [
  { label: "待装卸单", value: rows.value.filter((row) => row.status === "待装卸").length },
  { label: "装卸中单", value: rows.value.filter((row) => row.status === "装卸中").length },
  { label: "超时单数", value: rows.value.filter((row) => row.status === "已超时").length },
])

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '装卸记录登记入口尚未接入审批流'
}

function toggleSelect(id: number) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function toggleSelectAll() {
  if (allSelected.value) {
    const pageIds = rows.value.map((row) => Number(row.id))
    selectedIds.value = selectedIds.value.filter((id) => !pageIds.includes(id))
  } else {
    const merged = new Set([...selectedIds.value, ...rows.value.map((row) => Number(row.id))])
    selectedIds.value = [...merged]
  }
}

// ---- 批量更新弹层 ----
const batchOpen = ref(false)
const batchDrafts = ref<BatchDraft[]>([])
const batchId = ref('')
const batchSubmitting = ref(false)
const batchRetrying = ref(false)
const batchError = ref('')
const batchMessage = ref('')

const batchValid = computed(() =>
  batchDrafts.value.every(
    (draft) =>
      options.value.loadingTypes.includes(draft['装卸类型'])
      && typeof draft['开门时长'] === 'number'
      && Number.isInteger(draft['开门时长'])
      && draft['开门时长'] >= 0
      && options.value.waybillStatuses.includes(draft['运单状态']),
  ),
)

function newBatchId(): string {
  return `BATCH-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function openBatch() {
  batchDrafts.value = rows.value
    .filter((row) => selectedIds.value.includes(Number(row.id)))
    .map((row) => ({
      id: Number(row.id),
      记录编号: String(row['记录编号'] ?? ''),
      运单编号: String(row['运单编号'] ?? ''),
      装卸类型: options.value.loadingTypes.includes(String(row['装卸类型'])) ? String(row['装卸类型']) : '',
      开门时长: typeof row['开门时长'] === 'number' ? row['开门时长'] : Number(row['开门时长']) || 0,
      运单状态: options.value.waybillStatuses.includes(String(row['运单状态'])) ? String(row['运单状态']) : '',
    }))
  // 每次打开都是一批新提交；只有网络中断后的「继续提交」复用同一批次号。
  batchId.value = newBatchId()
  batchError.value = ''
  batchMessage.value = ''
  batchRetrying.value = false
  batchOpen.value = true
}

function closeBatch() {
  if (batchSubmitting.value) return
  batchOpen.value = false
}

async function submitBatch() {
  batchSubmitting.value = true
  batchError.value = ''
  batchMessage.value = ''
  const payload = {
    批次号: batchId.value,
    items: batchDrafts.value.map((draft) => ({
      记录id: draft.id,
      装卸类型: draft['装卸类型'],
      开门时长: draft['开门时长'],
      运单状态: draft['运单状态'],
    })),
  }
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      let detail = `服务端返回 ${response.status}，本批未提交成功`
      try {
        const body = await response.json()
        if (typeof body?.detail === 'string') {
          detail = body.detail
        } else if (Array.isArray(body?.detail)) {
          detail = `提交数据格式有误（${body.detail.length} 处），请检查后重试`
        }
      } catch {
        // 非 JSON 错误体时保留状态码提示
      }
      throw new Error(detail)
    }
    const body = (await response.json()) as BatchResponse
    if (!body.ok) {
      // 业务校验失败：服务端已整批回滚，可修正后用同一批次号继续提交。
      batchError.value = body.message || '批量更新被服务端驳回，本批已回滚，请修正后继续提交'
      batchRetrying.value = true
      return
    }
    batchMessage.value = body.message
    selectedIds.value = []
    await reload()
    batchOpen.value = false
  } catch (error) {
    // 网络中断：请求结果未知，但服务端按批次幂等，重发同一批只会补写未完成项。
    batchError.value = `${error instanceof Error ? error.message : '网络中断'}：连接恢复后点「继续提交」，将只从未完成项继续，不会重复写入`
    batchRetrying.value = true
  } finally {
    batchSubmitting.value = false
  }
}

// ---- 作业明细抽屉 ----
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailEntry = ref<Row | null>(null)
const detailWaybill = ref<Row | null>(null)
const detailWaybillError = ref('')

async function viewDetail(row: Row) {
  detailOpen.value = true
  detailLoading.value = true
  detailEntry.value = row
  detailWaybill.value = null
  detailWaybillError.value = ''
  const entryId = Number(row.id)
  try {
    const [entryResponse, waybillResponse] = await Promise.all([
      request(`${ENDPOINT}/${entryId}`),
      request(`${ENDPOINT}/${entryId}/waybill`),
    ])
    if (entryResponse.ok) {
      detailEntry.value = (await entryResponse.json()) as Row
    }
    if (waybillResponse.ok) {
      detailWaybill.value = (await waybillResponse.json()) as Row
    } else {
      detailWaybillError.value = '关联运单不存在或该记录未绑定运单'
    }
  } catch {
    detailWaybillError.value = '运单详情读取失败，请稍后重试'
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  detailOpen.value = false
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('装卸作业动作未生效，请稍后重试')
    }
    const body = (await response.json()) as { ok?: boolean; message?: string }
    if (body.ok === false) {
      throw new Error(body.message || '装卸作业动作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '装卸作业操作失败'
  }
}

async function loadOptions() {
  try {
    const response = await request(`${ENDPOINT}/options`)
    if (response.ok) {
      const body = (await response.json()) as { 装卸类型?: string[]; 运单状态?: string[] }
      options.value = {
        loadingTypes: body['装卸类型'] ?? options.value.loadingTypes,
        waybillStatuses: body['运单状态'] ?? [],
      }
    }
  } catch {
    // 枚举拉取失败时保留装车/卸车兜底，运单状态为空会阻止提交并提示
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('装卸记录列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 翻页/刷新后剔除已经不在列表里的勾选项，避免对不可见记录提交。
    const visibleIds = new Set(rows.value.map((row) => Number(row.id)))
    selectedIds.value = selectedIds.value.filter((id) => visibleIds.has(id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '装卸作业列表读取失败'
  }
}

onMounted(() => {
  void loadOptions()
  void reload()
})
</script>

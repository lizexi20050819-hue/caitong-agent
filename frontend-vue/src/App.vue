<script setup>
import { computed, onMounted, ref } from 'vue'
import MarkdownContent from './components/MarkdownContent.vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const messages = ref([])
const conversations = ref([])
const activeConversationId = ref('')
const activeConversationStatus = ref('ready')
const input = ref('')
const loading = ref(false)
const loadingHistory = ref(false)
const error = ref('')

const canSend = computed(() => input.value.trim().length > 0 && !loading.value)

const statusLabel = computed(() => {
  if (!activeConversationId.value) return '新对话'
  if (loading.value || activeConversationStatus.value === 'pending') return '生成中…'
  return '已连接历史'
})

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `请求失败：${response.status}`)
  }

  return response.json()
}

function previewLabel(text, pending = false) {
  const base = (text || '').slice(0, 50)
  return pending ? `${base}（生成中…）` : base
}

function upsertConversation(conversationId, preview, status = 'ready') {
  const pending = status === 'pending'
  const entry = {
    conversation_id: conversationId,
    preview: previewLabel(preview, pending),
    status,
  }
  const index = conversations.value.findIndex((item) => item.conversation_id === conversationId)
  if (index >= 0) {
    conversations.value[index] = entry
  } else {
    conversations.value.unshift(entry)
  }
}

async function refreshConversations() {
  loadingHistory.value = true
  try {
    const data = await request('/api/chat/list')
    conversations.value = data.conversations || []
    const active = conversations.value.find((item) => item.conversation_id === activeConversationId.value)
    if (active) {
      activeConversationStatus.value = active.status || 'ready'
    }
  } catch (err) {
    error.value = `加载历史失败：${err.message}`
  } finally {
    loadingHistory.value = false
  }
}

function newConversation() {
  activeConversationId.value = ''
  activeConversationStatus.value = 'ready'
  messages.value = []
  error.value = ''
}

async function loadConversation(conversationId) {
  if (loading.value || conversationId === activeConversationId.value) return

  error.value = ''
  try {
    const data = await request(`/api/chat/${conversationId}`)
    activeConversationId.value = data.conversation_id
    activeConversationStatus.value = data.status || 'ready'
    messages.value = (data.messages || []).map((message) => ({
      role: message.role,
      content: message.content,
      thinking: [],
      toolsUsed: [],
    }))
  } catch (err) {
    error.value = `打开对话失败：${err.message}`
  }
}

async function deleteConversation(conversationId) {
  error.value = ''
  try {
    await request(`/api/chat/${conversationId}`, { method: 'DELETE' })
    conversations.value = conversations.value.filter((item) => item.conversation_id !== conversationId)

    if (activeConversationId.value === conversationId) {
      newConversation()
    }
  } catch (err) {
    error.value = `删除对话失败：${err.message}`
  }
}

async function sendMessage() {
  const content = input.value.trim()
  if (!content || loading.value) return

  input.value = ''
  error.value = ''
  loading.value = true
  messages.value.push({ role: 'user', content, thinking: [], toolsUsed: [] })

  try {
    if (activeConversationId.value) {
      activeConversationStatus.value = 'pending'
      upsertConversation(activeConversationId.value, content, 'pending')

      const data = await request('/api/chat/continue', {
        method: 'POST',
        body: JSON.stringify({
          conversation_id: activeConversationId.value,
          message: content,
        }),
      })

      activeConversationStatus.value = 'ready'
      messages.value.push({
        role: 'assistant',
        content: data.response || 'Agent 未返回结果。',
        thinking: data.thinking || [],
        toolsUsed: data.tools_used || [],
      })
      await refreshConversations()
      return
    }

    const begun = await request('/api/chat/begin', {
      method: 'POST',
      body: JSON.stringify({ message: content }),
    })

    activeConversationId.value = begun.conversation_id
    activeConversationStatus.value = 'pending'
    upsertConversation(begun.conversation_id, begun.preview || content, 'pending')

    const data = await request(`/api/chat/${begun.conversation_id}/run`, {
      method: 'POST',
    })

    activeConversationStatus.value = 'ready'
    messages.value.push({
      role: 'assistant',
      content: data.response || 'Agent 未返回结果。',
      thinking: data.thinking || [],
      toolsUsed: data.tools_used || [],
    })
    await refreshConversations()
  } catch (err) {
    error.value = `请求失败：${err.message}`
    messages.value.push({
      role: 'assistant',
      content: '请求失败，请确认后端已经启动：scripts/run_backend.ps1',
      thinking: [],
      toolsUsed: [],
    })
    if (activeConversationId.value) {
      await refreshConversations()
    }
  } finally {
    loading.value = false
  }
}

onMounted(refreshConversations)
</script>

<template>
  <main class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">财</span>
        <div>
          <h1>财通Agent</h1>
          <p>A 股 LLM 投研助手</p>
        </div>
      </div>

      <button class="primary-button" type="button" @click="newConversation">新对话</button>

      <div class="history-header">
        <span>历史对话</span>
        <button type="button" :disabled="loadingHistory" @click="refreshConversations">
          {{ loadingHistory ? '刷新中' : '刷新' }}
        </button>
      </div>

      <div class="conversation-list">
        <p v-if="!conversations.length" class="empty-hint">暂无历史，先问一个问题。</p>

        <article
          v-for="conversation in conversations"
          :key="conversation.conversation_id"
          class="conversation-item"
          :class="{
            active: conversation.conversation_id === activeConversationId,
            pending: conversation.status === 'pending',
          }"
        >
          <button
            type="button"
            :disabled="loading"
            @click="loadConversation(conversation.conversation_id)"
          >
            {{ conversation.preview || conversation.conversation_id }}
          </button>
          <button
            class="delete-button"
            type="button"
            title="删除对话"
            :disabled="loading"
            @click="deleteConversation(conversation.conversation_id)"
          >
            删除
          </button>
        </article>
      </div>
    </aside>

    <section class="chat-panel">
      <header class="chat-header">
        <div>
          <p class="eyebrow">多轮对话</p>
          <h2>输入股票、ETF 或追问上下文</h2>
        </div>
        <span class="status-pill" :class="{ pending: statusLabel === '生成中…' }">{{ statusLabel }}</span>
      </header>

      <p v-if="error" class="error-banner">{{ error }}</p>

      <div class="messages">
        <div v-if="!messages.length" class="welcome-card">
          <h3>可以这样问</h3>
          <button type="button" @click="input = '分析一下贵州茅台'">分析一下贵州茅台</button>
          <button type="button" @click="input = '沪深300ETF 值得买吗'">沪深300ETF 值得买吗</button>
          <button type="button" @click="input = '600519 北向资金怎么看'">600519 北向资金怎么看</button>
        </div>

        <article v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
          <div class="message-role">{{ message.role === 'user' ? '你' : 'Agent' }}</div>
          <MarkdownContent
            v-if="message.role === 'assistant'"
            class="message-content"
            :content="message.content"
          />
          <p v-else class="message-content">{{ message.content }}</p>

          <details v-if="message.thinking?.length" class="thinking">
            <summary>调用了 {{ message.toolsUsed.length }} 个工具</summary>
            <pre v-for="(step, stepIndex) in message.thinking" :key="stepIndex">{{ step }}</pre>
          </details>
        </article>

        <article v-if="loading" class="message assistant">
          <div class="message-role">Agent</div>
          <p class="message-content">思考中，请稍等...</p>
        </article>
      </div>

      <form class="composer" @submit.prevent="sendMessage">
        <textarea
          v-model="input"
          rows="2"
          placeholder="输入你的问题，例如：分析一下贵州茅台"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <button type="submit" :disabled="!canSend">{{ loading ? '发送中' : '发送' }}</button>
      </form>
    </section>
  </main>
</template>

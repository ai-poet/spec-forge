import { useCallback, useEffect, useRef, useState } from 'react'
import { getIteration } from '../../../shared/lib/api'
import type { IterationDetail, LiveConnectionStatus, LiveMessage } from '../../../shared/lib/types'

const API_BASE = 'http://127.0.0.1:8787'

export function useIterationLive(iterationId: string | null) {
  const [detail, setDetail] = useState<IterationDetail | null>(null)
  const [docName, setDocName] = useState('system_design')
  const [docText, setDocText] = useState('')
  const [liveError, setLiveError] = useState<string | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<LiveConnectionStatus>('idle')
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null)
  const docNameRef = useRef(docName)

  useEffect(() => {
    docNameRef.current = docName
  }, [docName])

  const loadDocument = useCallback(
    async (name: string) => {
      if (!iterationId) return
      setDocName(name)
      const response = await fetch(`${API_BASE}/api/iterations/${iterationId}/documents/${name}`)
      if (!response.ok) throw new Error('文档读取失败，请刷新后重试。')
      const json = await response.json()
      setDocText(json.content)
    },
    [iterationId],
  )

  const loadDetail = useCallback(async () => {
    if (!iterationId) {
      setDetail(null)
      setDocText('')
      return
    }
    const data = await getIteration(iterationId)
    setDetail(data)
    const doc = data.documents.find((item) => item.name === docNameRef.current) ?? data.documents[0]
    if (doc) {
      await loadDocument(doc.name)
    } else {
      setDocText('')
    }
  }, [iterationId, loadDocument])

  useEffect(() => {
    loadDetail().catch(console.error)
  }, [loadDetail])

  useEffect(() => {
    if (!iterationId) {
      setConnectionStatus('idle')
      return
    }
    let closed = false
    let retry = 0
    let socket: WebSocket | null = null

    function connect() {
      setConnectionStatus(retry ? 'reconnecting' : 'connecting')
      socket = new WebSocket(`ws://127.0.0.1:8787/ws/iterations/${iterationId}`)
      socket.onopen = () => {
        retry = 0
        setConnectionStatus('connected')
      }
      socket.onmessage = async (event) => {
        try {
          const message = JSON.parse(event.data) as LiveMessage
          const snapshot = message.snapshot
          if (!snapshot) return
          setDetail(snapshot)
          setLastMessageAt(new Date().toISOString())
          setLiveError(null)
          const doc = snapshot.documents.find((item) => item.name === docNameRef.current) ?? snapshot.documents[0]
          if (doc) {
            const response = await fetch(`${API_BASE}/api/iterations/${iterationId}/documents/${doc.name}`)
            if (!response.ok) throw new Error('文档读取失败，请刷新后重试。')
            const json = await response.json()
            setDocText(json.content)
            if (doc.name !== docNameRef.current) {
              setDocName(doc.name)
            }
          } else {
            setDocText('')
          }
        } catch (error) {
          setLiveError(error instanceof Error ? error.message : String(error))
        }
      }
      socket.onerror = () => setLiveError('实时连接异常，正在尝试恢复。')
      socket.onclose = () => {
        if (closed) return
        retry += 1
        setLiveError('实时连接断开，正在重连')
        setConnectionStatus('reconnecting')
        window.setTimeout(connect, Math.min(10000, 500 * 2 ** retry))
      }
    }

    connect()
    return () => {
      closed = true
      setConnectionStatus('disconnected')
      socket?.close()
    }
  }, [iterationId])

  return {
    detail,
    docName,
    docText,
    liveError,
    connectionStatus,
    lastMessageAt,
    loadDetail,
    loadDocument,
  }
}

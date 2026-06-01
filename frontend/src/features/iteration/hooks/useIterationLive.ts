import { useCallback, useEffect, useRef, useState } from 'react'
import { getIteration, getIterationDocument } from '../../../shared/lib/api'
import { iterationWebSocketUrl } from '../../../shared/lib/wsUrl'
import type { CliOutputPayload, IterationDetail, LiveConnectionStatus, LiveMessage } from '../../../shared/lib/types'

function documentsMetaKey(documents: IterationDetail['documents'] | undefined): string {
  return (documents ?? []).map((item) => `${item.name}:${item.checksum}`).join('|')
}

async function syncDocumentText(
  iterationId: string,
  documents: IterationDetail['documents'] | undefined,
  preferredName: string,
): Promise<{ name: string; content: string } | null> {
  const doc = (documents ?? []).find((item) => item.name === preferredName) ?? (documents ?? [])[0]
  if (!doc) return null
  const content = await getIterationDocument(iterationId, doc.name)
  return { name: doc.name, content }
}

function isCliOutputEvent(event: LiveMessage['event']): event is { type: 'cli.output'; payload: CliOutputPayload } {
  return Boolean(event && event.type === 'cli.output' && 'payload' in event)
}

export function useIterationLive(iterationId: string | null) {
  const [detail, setDetail] = useState<IterationDetail | null>(null)
  const [docName, setDocName] = useState('system_design')
  const [docText, setDocText] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [liveError, setLiveError] = useState<string | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<LiveConnectionStatus>('idle')
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null)
  const docNameRef = useRef(docName)
  const documentsMetaRef = useRef('')

  useEffect(() => {
    docNameRef.current = docName
  }, [docName])

  const loadDocument = useCallback(
    async (name: string) => {
      if (!iterationId) return
      setDocName(name)
      setDocText(await getIterationDocument(iterationId, name))
    },
    [iterationId],
  )

  const loadDetail = useCallback(async () => {
    if (!iterationId) {
      setDetail(null)
      setDocText('')
      documentsMetaRef.current = ''
      setIsLoading(false)
      return
    }
    setIsLoading(true)
    try {
      const data = await getIteration(iterationId)
      setDetail(data)
      documentsMetaRef.current = documentsMetaKey(data.documents)
      const doc = data.documents.find((item) => item.name === docNameRef.current) ?? data.documents[0]
      if (doc) {
        await loadDocument(doc.name)
      } else {
        setDocText('')
      }
    } finally {
      setIsLoading(false)
    }
  }, [iterationId, loadDocument])

  useEffect(() => {
    if (!iterationId) return
    setDetail(null)
    setDocText('')
    setIsLoading(true)
  }, [iterationId])

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
      socket = new WebSocket(iterationWebSocketUrl(iterationId))
      socket.onopen = () => {
        retry = 0
        setConnectionStatus('connected')
      }
      socket.onmessage = async (event) => {
        try {
          const message = JSON.parse(event.data) as LiveMessage
          if (message.type === 'cli.output' && isCliOutputEvent(message.event)) {
            const { node, stream, chunk } = message.event.payload
            setDetail((prev) => {
              if (!prev) return prev
              const existing = prev.live_cli ?? { node, stdout: '', stderr: '' }
              return {
                ...prev,
                live_cli: {
                  node,
                  stdout: stream === 'stdout' ? existing.stdout + chunk : existing.stdout,
                  stderr: stream === 'stderr' ? existing.stderr + chunk : existing.stderr,
                },
              }
            })
            setLastMessageAt(new Date().toISOString())
            setLiveError(null)
            return
          }

          const snapshot = message.snapshot
          if (!snapshot) return
          setDetail(snapshot)
          setLastMessageAt(new Date().toISOString())
          setLiveError(null)

          const nextMeta = documentsMetaKey(snapshot.documents)
          if (nextMeta === documentsMetaRef.current) return
          documentsMetaRef.current = nextMeta

          try {
            const synced = await syncDocumentText(iterationId, snapshot.documents, docNameRef.current)
            if (synced) {
              setDocText(synced.content)
              if (synced.name !== docNameRef.current) {
                setDocName(synced.name)
              }
            } else {
              setDocText('')
            }
          } catch (error) {
            console.warn('文档同步失败', error)
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
    isLoading,
    liveError,
    connectionStatus,
    lastMessageAt,
    loadDetail,
    loadDocument,
  }
}

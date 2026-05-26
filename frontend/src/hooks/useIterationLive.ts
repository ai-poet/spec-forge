import { useCallback, useEffect, useRef, useState } from 'react'
import { getIteration } from '../api'
import type { IterationDetail } from '../types'

const API_BASE = 'http://127.0.0.1:8787'

export function useIterationLive(iterationId: string | null) {
  const [detail, setDetail] = useState<IterationDetail | null>(null)
  const [docName, setDocName] = useState('system_design')
  const [docText, setDocText] = useState('')
  const [liveError, setLiveError] = useState<string | null>(null)
  const docNameRef = useRef(docName)

  useEffect(() => {
    docNameRef.current = docName
  }, [docName])

  const loadDocument = useCallback(
    async (name: string) => {
      if (!iterationId) return
      setDocName(name)
      const response = await fetch(`${API_BASE}/api/iterations/${iterationId}/documents/${name}`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
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
    if (!iterationId) return
    const socket = new WebSocket(`ws://127.0.0.1:8787/ws/iterations/${iterationId}`)
    socket.onmessage = async (event) => {
      try {
        const snapshot = JSON.parse(event.data) as IterationDetail
        setDetail(snapshot)
        setLiveError(null)
        const doc = snapshot.documents.find((item) => item.name === docNameRef.current) ?? snapshot.documents[0]
        if (doc) {
          const response = await fetch(`${API_BASE}/api/iterations/${iterationId}/documents/${doc.name}`)
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
    socket.onerror = () => setLiveError('Live feed disconnected')
    return () => socket.close()
  }, [iterationId])

  return {
    detail,
    docName,
    docText,
    liveError,
    loadDetail,
    loadDocument,
  }
}

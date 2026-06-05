import { useEffect, useState } from 'react'
import {
  createProjectProfile,
  deleteProjectProfile,
  getProfileBindings,
  listProjectProfiles,
  updateProfileBindings,
  updateProjectProfile,
} from '../../../shared/lib/api'
import type { CliBindingProvider, CliBindings, EnvironmentCheckItem, ProjectProfile, ProjectSummary, StageProfileBindings, UpdateProjectInput } from '../../../shared/lib/types'
import { DEFAULT_CLI_BINDINGS } from '../../../shared/lib/types'
import { EnvironmentCheckPanel } from '../EnvironmentCheckPanel'
import { ProjectFolderPanel } from '../ProjectFolderPanel'

interface Props {
  project: ProjectSummary | null
  busy: boolean
  onSave: (projectId: string, input: UpdateProjectInput) => Promise<void>
  onBindFolder: (projectId: string, rootPath: string, createIfMissing: boolean) => Promise<void>
  onDelete: (projectId: string) => Promise<void>
}

const STAGE_LABELS: { key: keyof CliBindings; label: string }[] = [
  { key: 'planner_discovery', label: '需求澄清' },
  { key: 'prd_planner', label: 'PRD 规划' },
  { key: 'test_planner', label: '测试规划' },
  { key: 'planner_clarification', label: '规划澄清' },
  { key: 'coder', label: '实现 (Coder)' },
  { key: 'code_tester', label: '代码验证' },
  { key: 'ui_tester', label: 'UI 验证' },
]

function mergeBindings(project: ProjectSummary | null): CliBindings {
  return { ...DEFAULT_CLI_BINDINGS, ...(project?.cli_bindings ?? {}) }
}

const EMPTY_PROFILE = { id: '', name: '', summary: '', stage: 'coder', content: '' }

export function ProjectConfigPanel({ project, busy, onSave, onBindFolder, onDelete }: Props) {
  const [defaultTestCommand, setDefaultTestCommand] = useState('')
  const [coderRetries, setCoderRetries] = useState(5)
  const [clarifications, setClarifications] = useState(3)
  const [verifyRejects, setVerifyRejects] = useState(2)
  const [cliBindings, setCliBindings] = useState<CliBindings>(DEFAULT_CLI_BINDINGS)
  const [providerChecks, setProviderChecks] = useState<EnvironmentCheckItem[]>([])
  const [profiles, setProfiles] = useState<ProjectProfile[]>([])
  const [profileBindings, setProfileBindings] = useState<StageProfileBindings>({})
  const [profileDraft, setProfileDraft] = useState(EMPTY_PROFILE)
  const [profileBusy, setProfileBusy] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)

  useEffect(() => {
    if (!project) return
    setDefaultTestCommand(project.default_test_command ?? '')
    setCoderRetries(project.max_coder_tester_retries)
    setClarifications(project.max_clarifications)
    setVerifyRejects(project.max_verify_rejects)
    setCliBindings(mergeBindings(project))
    loadProfiles(project.id).catch(console.error)
  }, [project])

  async function loadProfiles(projectId: string) {
    setProfileError(null)
    const [items, bindings] = await Promise.all([
      listProjectProfiles(projectId),
      getProfileBindings(projectId),
    ])
    setProfiles(items)
    setProfileBindings(bindings.bindings)
  }

  async function handleSave() {
    if (!project) return
    await onSave(project.id, {
      default_test_command: defaultTestCommand.trim() || null,
      cli_bindings: cliBindings,
      max_coder_tester_retries: coderRetries,
      max_clarifications: clarifications,
      max_verify_rejects: verifyRejects,
    })
  }

  function updateBinding(stage: keyof CliBindings, provider: CliBindingProvider) {
    setCliBindings((prev) => ({ ...prev, [stage]: provider }))
  }

  function editProfile(profile: ProjectProfile) {
    setProfileDraft({
      id: profile.id,
      name: profile.name,
      summary: profile.summary,
      stage: profile.stage,
      content: profile.content,
    })
  }

  function resetProfileDraft() {
    setProfileDraft(EMPTY_PROFILE)
  }

  async function saveProfile() {
    if (!project) return
    setProfileBusy(true)
    setProfileError(null)
    try {
      const input = {
        name: profileDraft.name.trim(),
        summary: profileDraft.summary.trim(),
        stage: profileDraft.stage,
        content: profileDraft.content.trim(),
      }
      if (profileDraft.id) {
        await updateProjectProfile(project.id, profileDraft.id, input)
      } else {
        await createProjectProfile(project.id, input)
      }
      resetProfileDraft()
      await loadProfiles(project.id)
    } catch (exc) {
      setProfileError(exc instanceof Error ? exc.message : 'Profile 保存失败')
    } finally {
      setProfileBusy(false)
    }
  }

  async function removeProfile(profile: ProjectProfile) {
    if (!project) return
    const confirmed = window.confirm(`删除 Profile「${profile.name}」？绑定到阶段的引用会自动清理。`)
    if (!confirmed) return
    setProfileBusy(true)
    setProfileError(null)
    try {
      await deleteProjectProfile(project.id, profile.id)
      if (profileDraft.id === profile.id) resetProfileDraft()
      await loadProfiles(project.id)
    } catch (exc) {
      setProfileError(exc instanceof Error ? exc.message : 'Profile 删除失败')
    } finally {
      setProfileBusy(false)
    }
  }

  async function bindProfile(stage: keyof CliBindings, profileId: string) {
    if (!project) return
    const next = { ...profileBindings, [stage]: profileId || null }
    setProfileBindings(next)
    setProfileError(null)
    try {
      const result = await updateProfileBindings(project.id, next)
      setProfileBindings(result.bindings)
    } catch (exc) {
      setProfileError(exc instanceof Error ? exc.message : 'Profile 绑定失败')
      await loadProfiles(project.id)
    }
  }

  async function handleDelete() {
    if (!project) return
    const confirmed = window.confirm(
      `确定从 SpecForge 移除「${project.name}」？\n\n本地文件夹不会被删除，只是不再出现在项目列表中。`,
    )
    if (!confirmed) return
    await onDelete(project.id)
  }

  return (
    <>
    <ProjectFolderPanel project={project} busy={busy} onBind={onBindFolder} />
    <EnvironmentCheckPanel onChecksChange={setProviderChecks} />

    <section className="surface stack">
      <div className="section-row">
        <div>
          <h2 className="section-title">上下文 / Profile</h2>
          <p className="muted">项目级 Profile 会追加到对应阶段 Prompt，不覆盖 SpecForge 内置阶段约束。</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={resetProfileDraft} disabled={!project || profileBusy}>
          新建 Profile
        </button>
      </div>
      {profileError ? <div className="error-text">{profileError}</div> : null}
      <div className="profile-layout">
        <div className="profile-list">
          {profiles.length ? profiles.map((profile) => (
            <article key={profile.id} className="profile-card">
              <div>
                <strong>{profile.name}</strong>
                <span className="muted">{profile.id} · {STAGE_LABELS.find((item) => item.key === profile.stage)?.label ?? profile.stage}</span>
              </div>
              {profile.summary ? <p>{profile.summary}</p> : null}
              <div className="actions">
                <button type="button" className="btn btn-sm" onClick={() => editProfile(profile)} disabled={profileBusy}>编辑</button>
                <button type="button" className="btn danger btn-sm" onClick={() => removeProfile(profile)} disabled={profileBusy}>删除</button>
              </div>
            </article>
          )) : <div className="empty">暂无项目级 Profile。</div>}
        </div>
        <div className="profile-editor">
          <label>
            <span>名称</span>
            <input value={profileDraft.name} onChange={(event) => setProfileDraft((prev) => ({ ...prev, name: event.target.value }))} disabled={!project || profileBusy} />
          </label>
          <label>
            <span>阶段</span>
            <select value={profileDraft.stage} onChange={(event) => setProfileDraft((prev) => ({ ...prev, stage: event.target.value }))} disabled={!project || profileBusy}>
              {STAGE_LABELS.map(({ key, label }) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <label>
            <span>摘要</span>
            <input value={profileDraft.summary} onChange={(event) => setProfileDraft((prev) => ({ ...prev, summary: event.target.value }))} disabled={!project || profileBusy} />
          </label>
          <label>
            <span>内容</span>
            <textarea rows={7} value={profileDraft.content} onChange={(event) => setProfileDraft((prev) => ({ ...prev, content: event.target.value }))} disabled={!project || profileBusy} />
          </label>
          <button type="button" className="btn primary" onClick={saveProfile} disabled={!project || profileBusy || !profileDraft.name.trim() || !profileDraft.content.trim()}>
            {profileDraft.id ? '保存 Profile' : '创建 Profile'}
          </button>
        </div>
      </div>
      <div className="config-grid">
        {STAGE_LABELS.map(({ key, label }) => (
          <label key={key}>
            <span>{label} Profile</span>
            <select value={profileBindings[key] ?? ''} onChange={(event) => bindProfile(key, event.target.value)} disabled={!project || profileBusy}>
              <option value="">未绑定</option>
              {profiles.filter((profile) => profile.stage === key).map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </section>

    <section className="surface stack">
      <div className="section-row">
        <div>
          <h2 className="section-title">Agent / Provider</h2>
          <p className="muted">为各环节选择 CLI provider；Provider 卡片展示本机 doctor 状态和能力。</p>
        </div>
        <button type="button" className="btn primary" onClick={handleSave} disabled={busy || !project}>
          保存配置
        </button>
      </div>
      <div className="provider-grid">
        {(['claude', 'codex'] as const).map((provider) => {
          const check = providerChecks.find((item) => item.provider === provider || item.id === `provider_${provider}`)
          const capabilities = check?.capabilities ?? {}
          return (
            <article key={provider} className="provider-card">
              <div className="section-row">
                <div>
                  <strong>{provider === 'claude' ? 'Claude Code' : 'Codex CLI'}</strong>
                  <div className="muted">{check?.version ?? check?.detail ?? '尚未检测'}</div>
                </div>
                <span className={`status-dot ${check?.status ?? 'warning'}`}>{check?.status === 'ok' ? '可用' : '需检查'}</span>
              </div>
              <div className="provider-capabilities">
                <span>continue {capabilities.supports_continue_session ? 'yes' : 'best-effort'}</span>
                <span>raw stream {capabilities.supports_raw_stream ? 'yes' : 'yes'}</span>
                <span>prompt bundle {capabilities.supports_prompt_bundle ? 'yes' : 'yes'}</span>
              </div>
              {check?.hint ? <code className="inline-code">{check.hint}</code> : null}
            </article>
          )
        })}
      </div>
      <div className="config-grid">
        <label>
          <span>默认测试命令</span>
          <input value={defaultTestCommand} onChange={(event) => setDefaultTestCommand(event.target.value)} placeholder="pytest" disabled={!project} />
        </label>
        <label>
          <span>Coder/Tester 重试上限</span>
          <input type="number" min="0" max="20" value={coderRetries} onChange={(event) => setCoderRetries(Number(event.target.value))} disabled={!project} />
        </label>
        <label>
          <span>澄清上限</span>
          <input type="number" min="0" max="20" value={clarifications} onChange={(event) => setClarifications(Number(event.target.value))} disabled={!project} />
        </label>
        <label>
          <span>规格复核驳回上限</span>
          <input type="number" min="0" max="20" value={verifyRejects} onChange={(event) => setVerifyRejects(Number(event.target.value))} disabled={!project} />
        </label>
      </div>
      <div className="config-grid">
        {STAGE_LABELS.map(({ key, label }) => (
          <label key={key}>
            <span>{label}</span>
            <select
              value={cliBindings[key]}
              onChange={(event) => updateBinding(key, event.target.value as CliBindingProvider)}
              disabled={!project}
            >
              <option value="claude">Claude Code</option>
              <option value="codex">Codex</option>
            </select>
          </label>
        ))}
      </div>
    </section>

    <section className="surface stack danger-zone">
      <div className="section-row">
        <div>
          <h2 className="section-title">移除项目</h2>
          <p className="muted">从 SpecForge 项目列表中移除，不会删除本地文件夹或 `.specforge` 产物。</p>
        </div>
        <button type="button" className="btn danger btn-sm" onClick={handleDelete} disabled={busy || !project}>
          从 SpecForge 移除
        </button>
      </div>
    </section>
    </>
  )
}

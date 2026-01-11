import { useState, type FormEvent } from 'react'
import { X, GitBranch, Loader2 } from 'lucide-react'
import { useCloneProject, useGithubSshStatus } from '../hooks/useProjects'

interface CloneRepoModalProps {
  isOpen: boolean
  onClose: () => void
  onProjectCloned: (projectName: string) => void
  onOpenSettings: () => void
}

export function CloneRepoModal({ isOpen, onClose, onProjectCloned, onOpenSettings }: CloneRepoModalProps) {
  const [projectName, setProjectName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cloneProject = useCloneProject()
  const { data: githubSshStatus, isLoading: githubSshLoading } = useGithubSshStatus()

  if (!isOpen) return null

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const name = projectName.trim()
    const url = repoUrl.trim()

    if (!name) {
      setError('Please enter a project name')
      return
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
      setError('Project name can only contain letters, numbers, hyphens, and underscores')
      return
    }
    if (!url) {
      setError('Please enter a repo SSH URL')
      return
    }

    setError(null)
    try {
      const project = await cloneProject.mutateAsync({ name, repoUrl: url })
      onProjectCloned(project.name)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clone repository')
    }
  }

  return (
    <div className="neo-modal-backdrop" onClick={onClose}>
      <div className="neo-modal w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b-3 border-[var(--color-neo-border)]">
          <h2 className="font-display font-bold text-xl text-[#1a1a1a]">Import from GitHub</h2>
          <button onClick={onClose} className="neo-btn neo-btn-ghost p-2">
            <X size={20} />
          </button>
        </div>

        <form className="p-6" onSubmit={handleSubmit}>
          <div className="mb-4 p-3 bg-white border-3 border-[var(--color-neo-border)] text-sm">
            {githubSshLoading ? (
              <div className="flex items-center gap-2">
                <Loader2 size={16} className="animate-spin" />
                <span>Checking GitHub SSH key...</span>
              </div>
            ) : githubSshStatus?.configured ? (
              <div>
                <div className="font-bold">GitHub SSH key: Configured</div>
                {githubSshStatus.fingerprint && (
                  <div className="text-[var(--color-neo-text-secondary)]">
                    Fingerprint: <span className="font-mono">{githubSshStatus.fingerprint}</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="font-bold">GitHub SSH key: Not configured</div>
                  <div className="text-[var(--color-neo-text-secondary)]">
                    Set your <span className="font-mono">id_rsa</span> in Settings to clone/push.
                  </div>
                </div>
                <button type="button" className="neo-btn" onClick={onOpenSettings}>
                  Open Settings
                </button>
              </div>
            )}
          </div>

          <div className="mb-4">
            <label className="block font-bold mb-2 text-[#1a1a1a]">Project Name</label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="my-repo"
              className="neo-input"
              pattern="^[a-zA-Z0-9_-]+$"
              autoFocus
            />
            <p className="text-sm text-[var(--color-neo-text-secondary)] mt-2">
              This will clone into <span className="font-mono">/app/generations/&lt;name&gt;</span>
            </p>
          </div>

          <div className="mb-4">
            <label className="block font-bold mb-2 text-[#1a1a1a]">GitHub Repo (HTTPS or SSH)</label>
            <input
              type="text"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/owner/repo or git@github.com:owner/repo.git"
              className="neo-input"
            />
            <p className="text-sm text-[var(--color-neo-text-secondary)] mt-2">
              We will convert HTTPS to SSH internally. Requires GitHub SSH key configured in Settings.
            </p>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-[var(--color-neo-danger)] text-white text-sm border-2 border-[var(--color-neo-border)]">
              {error}
            </div>
          )}

          <button type="submit" className="neo-btn neo-btn-primary w-full" disabled={cloneProject.isPending}>
            {cloneProject.isPending ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Cloning...
              </>
            ) : (
              <>
                <GitBranch size={16} />
                Clone Repo
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  )
}

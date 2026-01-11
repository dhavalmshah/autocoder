import { useEffect, useRef, useState } from 'react'
import { X, Loader2, AlertCircle } from 'lucide-react'
import {
  useSettings,
  useUpdateSettings,
  useAvailableModels,
  useGithubSshStatus,
  useSetGithubSshKey,
  useUploadGithubSshKeyFile,
  useTestGithubSsh,
} from '../hooks/useProjects'

interface SettingsModalProps {
  onClose: () => void
}

export function SettingsModal({ onClose }: SettingsModalProps) {
  const { data: settings, isLoading, isError, refetch } = useSettings()
  const { data: modelsData } = useAvailableModels()
  const updateSettings = useUpdateSettings()
  const { data: githubSshStatus, isLoading: githubSshLoading, refetch: refetchGithubSshStatus } = useGithubSshStatus()
  const setGithubSshKey = useSetGithubSshKey()
  const uploadGithubSshKeyFile = useUploadGithubSshKeyFile()
  const testGithubSsh = useTestGithubSsh()
  const [githubPrivateKey, setGithubPrivateKey] = useState('')
  const [githubKeyFile, setGithubKeyFile] = useState<File | null>(null)
  const [githubMessage, setGithubMessage] = useState<string | null>(null)
  const [githubTestOutput, setGithubTestOutput] = useState<string | null>(null)
  const modalRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  // Focus trap - keep focus within modal
  useEffect(() => {
    const modal = modalRef.current
    if (!modal) return

    // Focus the close button when modal opens
    closeButtonRef.current?.focus()

    const focusableElements = modal.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]

    const handleTabKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault()
          lastElement?.focus()
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault()
          firstElement?.focus()
        }
      }
    }

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('keydown', handleTabKey)
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('keydown', handleTabKey)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [onClose])

  const handleYoloToggle = () => {
    if (settings && !updateSettings.isPending) {
      updateSettings.mutate({ yolo_mode: !settings.yolo_mode })
    }
  }

  const handleModelChange = (modelId: string) => {
    if (!updateSettings.isPending) {
      updateSettings.mutate({ model: modelId })
    }
  }

  const models = modelsData?.models ?? []
  const isSaving = updateSettings.isPending

  const handleSaveGithubKey = async () => {
    setGithubMessage(null)
    setGithubTestOutput(null)
    try {
      await setGithubSshKey.mutateAsync(githubPrivateKey)
      setGithubMessage('Saved GitHub SSH key')
      setGithubPrivateKey('')
      await refetchGithubSshStatus()
    } catch (e) {
      setGithubMessage(e instanceof Error ? e.message : 'Failed to save key')
    }
  }

  const handleUploadGithubKey = async () => {
    if (!githubKeyFile) return
    setGithubMessage(null)
    setGithubTestOutput(null)
    try {
      await uploadGithubSshKeyFile.mutateAsync(githubKeyFile)
      setGithubMessage('Uploaded GitHub SSH key')
      setGithubKeyFile(null)
      await refetchGithubSshStatus()
    } catch (e) {
      setGithubMessage(e instanceof Error ? e.message : 'Failed to upload key')
    }
  }

  const handleTestGithubSsh = async () => {
    setGithubMessage(null)
    setGithubTestOutput(null)
    try {
      const result = await testGithubSsh.mutateAsync()
      setGithubTestOutput(result.output)
      setGithubMessage(result.success ? 'GitHub SSH test succeeded' : 'GitHub SSH test failed')
    } catch (e) {
      setGithubMessage(e instanceof Error ? e.message : 'GitHub SSH test failed')
    }
  }

  return (
    <div
      className="neo-modal-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={modalRef}
        className="neo-modal w-full max-w-sm p-6"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="settings-title"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 id="settings-title" className="font-display text-xl font-bold">
            Settings
            {isSaving && (
              <Loader2 className="inline-block ml-2 animate-spin" size={16} />
            )}
          </h2>
          <button
            ref={closeButtonRef}
            onClick={onClose}
            className="neo-btn neo-btn-ghost p-2"
            aria-label="Close settings"
          >
            <X size={20} />
          </button>
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="animate-spin" size={24} />
            <span className="ml-2">Loading settings...</span>
          </div>
        )}

        {/* Error State */}
        {isError && (
          <div className="p-4 bg-[var(--color-neo-danger)] text-white border-3 border-[var(--color-neo-border)] mb-4">
            <div className="flex items-center gap-2">
              <AlertCircle size={18} />
              <span>Failed to load settings</span>
            </div>
            <button
              onClick={() => refetch()}
              className="mt-2 underline text-sm"
            >
              Retry
            </button>
          </div>
        )}

        {/* Settings Content */}
        {settings && !isLoading && (
          <div className="space-y-6">
            {/* YOLO Mode Toggle */}
            <div>
              <div className="flex items-center justify-between">
                <div>
                  <label
                    id="yolo-label"
                    className="font-display font-bold text-base"
                  >
                    YOLO Mode
                  </label>
                  <p className="text-sm text-[var(--color-neo-text-secondary)] mt-1">
                    Skip testing for rapid prototyping
                  </p>
                </div>
                <button
                  onClick={handleYoloToggle}
                  disabled={isSaving}
                  className={`relative w-14 h-8 rounded-none border-3 border-[var(--color-neo-border)] transition-colors ${
                    settings.yolo_mode
                      ? 'bg-[var(--color-neo-pending)]'
                      : 'bg-white'
                  } ${isSaving ? 'opacity-50 cursor-not-allowed' : ''}`}
                  role="switch"
                  aria-checked={settings.yolo_mode}
                  aria-labelledby="yolo-label"
                >
                  <span
                    className={`absolute top-1 w-5 h-5 bg-[var(--color-neo-border)] transition-transform ${
                      settings.yolo_mode ? 'left-7' : 'left-1'
                    }`}
                  />
                </button>
              </div>
            </div>

            {/* Model Selection - Radio Group */}
            <div>
              <label
                id="model-label"
                className="font-display font-bold text-base block mb-2"
              >
                Model
              </label>
              <div
                className="flex border-3 border-[var(--color-neo-border)]"
                role="radiogroup"
                aria-labelledby="model-label"
              >
                {models.map((model) => (
                  <button
                    key={model.id}
                    onClick={() => handleModelChange(model.id)}
                    disabled={isSaving}
                    role="radio"
                    aria-checked={settings.model === model.id}
                    className={`flex-1 py-3 px-4 font-display font-bold text-sm transition-colors ${
                      settings.model === model.id
                        ? 'bg-[var(--color-neo-accent)] text-white'
                        : 'bg-white text-[var(--color-neo-text)] hover:bg-gray-100'
                    } ${isSaving ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    {model.name}
                  </button>
                ))}
              </div>
            </div>

            {/* Update Error */}
            {updateSettings.isError && (
              <div className="p-3 bg-red-50 border-3 border-red-200 text-red-700 text-sm">
                Failed to save settings. Please try again.
              </div>
            )}

            <div>
              <div className="font-display font-bold text-base">GitHub SSH</div>
              <p className="text-sm text-[var(--color-neo-text-secondary)] mt-1">
                Configure a single SSH key for cloning/pushing to GitHub
              </p>

              <div className="mt-3 p-3 bg-white border-3 border-[var(--color-neo-border)] text-sm">
                {githubSshLoading ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="animate-spin" size={16} />
                    <span>Checking status...</span>
                  </div>
                ) : githubSshStatus?.configured ? (
                  <div>
                    <div className="font-bold">Configured</div>
                    {githubSshStatus.fingerprint && (
                      <div className="text-[var(--color-neo-text-secondary)]">
                        Fingerprint: <span className="font-mono">{githubSshStatus.fingerprint}</span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="font-bold">Not configured</div>
                )}
              </div>

              <div className="mt-4">
                <label className="font-display font-bold text-sm block mb-2">Paste private key</label>
                <textarea
                  value={githubPrivateKey}
                  onChange={(e) => setGithubPrivateKey(e.target.value)}
                  className="w-full h-24 p-3 border-3 border-[var(--color-neo-border)] bg-white font-mono text-xs"
                  placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                />
                <button
                  onClick={handleSaveGithubKey}
                  disabled={!githubPrivateKey.trim() || setGithubSshKey.isPending}
                  className="neo-btn neo-btn-primary w-full mt-2"
                >
                  {setGithubSshKey.isPending ? 'Saving...' : 'Save key'}
                </button>
              </div>

              <div className="mt-4">
                <label className="font-display font-bold text-sm block mb-2">Or upload key file</label>
                <input
                  type="file"
                  accept=".pem,.key,*/*"
                  onChange={(e) => setGithubKeyFile(e.target.files?.[0] ?? null)}
                  className="w-full"
                />
                <button
                  onClick={handleUploadGithubKey}
                  disabled={!githubKeyFile || uploadGithubSshKeyFile.isPending}
                  className="neo-btn neo-btn-primary w-full mt-2"
                >
                  {uploadGithubSshKeyFile.isPending ? 'Uploading...' : 'Upload key file'}
                </button>
              </div>

              <div className="mt-4">
                <button
                  onClick={handleTestGithubSsh}
                  disabled={testGithubSsh.isPending}
                  className="neo-btn neo-btn-success w-full"
                >
                  {testGithubSsh.isPending ? 'Testing...' : 'Test GitHub SSH'}
                </button>
              </div>

              {githubMessage && (
                <div className="mt-3 p-3 border-3 border-[var(--color-neo-border)] bg-[var(--color-neo-bg)] text-sm">
                  {githubMessage}
                </div>
              )}

              {githubTestOutput && (
                <pre className="mt-3 p-3 border-3 border-[var(--color-neo-border)] bg-white text-xs whitespace-pre-wrap break-words">
                  {githubTestOutput}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

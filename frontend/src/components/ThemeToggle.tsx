import { Sun, Moon } from 'lucide-react'
import { useTheme } from '@/contexts/ThemeContext'

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()

  return (
    <button
      onClick={toggleTheme}
      className="flex items-center justify-center w-8 h-8 rounded-lg transition-all"
      style={{
        color: 'var(--th-text-tertiary)',
        border: '1px solid var(--th-border-medium)',
        background: 'var(--th-glass-inset)',
        cursor: 'pointer',
      }}
      title={theme === 'dark' ? 'Mode clair' : 'Mode sombre'}
    >
      {theme === 'dark' ? (
        <Sun className="w-4 h-4" style={{ transition: 'transform 0.3s', transform: 'rotate(0deg)' }} />
      ) : (
        <Moon className="w-4 h-4" style={{ transition: 'transform 0.3s', transform: 'rotate(0deg)' }} />
      )}
    </button>
  )
}

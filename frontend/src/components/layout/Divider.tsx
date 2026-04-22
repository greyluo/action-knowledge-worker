import { useRef, useState, type CSSProperties } from 'react'

interface DividerProps {
  onResize: (delta: number) => void
}

function dividerStyle(active: boolean): CSSProperties {
  return {
    height: '5px',
    width: '100%',
    flexShrink: 0,
    background: active
      ? 'rgba(59,130,246,0.4)'
      : 'var(--color-border)',
    cursor: 'row-resize',
    transition: active ? 'none' : 'background 120ms',
    position: 'relative',
    zIndex: 10,
  }
}

export function Divider({ onResize }: DividerProps) {
  const [active, setActive] = useState(false)
  const isDragging = useRef(false)

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    setActive(true)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'row-resize'

    let prevY = e.clientY

    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return
      const delta = ev.clientY - prevY
      prevY = ev.clientY
      onResize(delta)
    }

    const onUp = () => {
      isDragging.current = false
      setActive(false)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  return (
    <div
      style={dividerStyle(active)}
      onMouseDown={handleMouseDown}
      onMouseEnter={() => { if (!isDragging.current) setActive(true) }}
      onMouseLeave={() => { if (!isDragging.current) setActive(false) }}
    />
  )
}

export default Divider

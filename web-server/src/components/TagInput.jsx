import { useRef, useState } from 'react'

export default function TagInput({ value, onChange, placeholder, disabled = false }) {
  const [text, setText] = useState('')
  const [editingIndex, setEditingIndex] = useState(null)
  const [editText, setEditText] = useState('')
  const skipBlurRef = useRef(false)
  const tags = Array.isArray(value) ? value : []

  function addMany(words) {
    const next = [...tags]
    for (const word of words) {
      const w = word.trim()
      if (w && !next.includes(w)) next.push(w)
    }
    if (next.length !== tags.length) onChange(next)
  }

  function commit() {
    addMany([text])
    setText('')
  }

  function handleChange(e) {
    const raw = e.target.value
    if (raw.includes(',')) {
      const parts = raw.split(',')
      const last = parts.pop()
      addMany(parts)
      setText(last)
    } else {
      setText(raw)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      commit()
    } else if (e.key === 'Backspace' && text === '' && tags.length > 0) {
      onChange(tags.slice(0, -1))
    }
  }

  function startEdit(index) {
    if (disabled) return
    skipBlurRef.current = false
    setEditingIndex(index)
    setEditText(tags[index])
  }

  function cancelEdit() {
    skipBlurRef.current = true
    setEditingIndex(null)
    setEditText('')
  }

  function commitEdit() {
    if (skipBlurRef.current) {
      skipBlurRef.current = false
      return
    }
    if (editingIndex === null) return
    const word = editText.trim()
    const next = [...tags]
    if (!word || next.some((t, i) => i !== editingIndex && t === word)) {
      next.splice(editingIndex, 1)
    } else {
      next[editingIndex] = word
    }
    onChange(next)
    cancelEdit()
  }

  function handleEditKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      commitEdit()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      cancelEdit()
    }
  }

  return (
    <div className="tag-input">
      <div className="tags">
        {tags.map((tag, index) => (
          editingIndex === index ? (
            <input
              key={`edit-${index}`}
              className="tag-edit"
              value={editText}
              autoFocus
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={handleEditKeyDown}
              onBlur={commitEdit}
            />
          ) : (
            <span
              className="tag"
              key={tag}
              title="Нажмите, чтобы изменить"
              onClick={() => startEdit(index)}
            >
              {tag}
              <button
                type="button"
                className="tag-remove"
                onClick={(e) => {
                  e.stopPropagation()
                  onChange(tags.filter((t) => t !== tag))
                }}
              >×</button>
            </span>
          )
        ))}
        <input
          className="tag-field"
          aria-label={placeholder}
          value={text}
          placeholder={tags.length === 0 ? placeholder : ''}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onBlur={commit}
        />
      </div>
    </div>
  )
}


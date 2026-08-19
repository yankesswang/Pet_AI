import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'

import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'

const el = document.getElementById('root')
if (!el) throw new Error('找不到 #root 掛載節點')

createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

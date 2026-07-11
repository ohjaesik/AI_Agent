// React application bootstrap.
// `index.html`의 #root element에 AX Delivery Planner SPA를 mount한다.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// StrictMode는 개발 중 effect 재실행 등을 통해 side effect 문제를 더 빨리 드러내준다.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

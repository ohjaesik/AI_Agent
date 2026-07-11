// Vite build/dev-server 설정.
// React plugin만 켜고, API proxy는 쓰지 않으며 `front/src/api.ts`의 VITE_API_BASE_URL을 따른다.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // JSX transform, Fast Refresh, React-specific compile option을 Vite에 연결한다.
  plugins: [react()],
})

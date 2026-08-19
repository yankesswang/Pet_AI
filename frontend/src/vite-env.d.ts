/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'false' 時切換到真實後端 API；其餘值（含未設定）皆使用 mock fixtures */
  readonly VITE_USE_MOCKS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

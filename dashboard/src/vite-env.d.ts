/// <reference types="vite/client" />

/** Build-time switches. All optional; see .env.example for what each one does. */
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_AGENT_BASE?: string;
  readonly VITE_DATA_MODE?: string;
  readonly VITE_READ_ONLY?: string;
  readonly VITE_ASK_FIXTURE?: string;
}

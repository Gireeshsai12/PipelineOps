import { defineConfig } from 'vite';

export default defineConfig({
  server: { proxy: { '/api': { target: process.env.PIPELINEOPS_API || 'http://127.0.0.1:8000' } } },
});

import { defineConfig } from '@tarojs/cli'

export default defineConfig({
  logger: {
    quiet: false,
    stats: true
  },
  mini: {},
  h5: {
    devServer: {
      host: '0.0.0.0',
      port: 10086,
      open: false,
      allowedHosts: 'all'
    }
  }
})
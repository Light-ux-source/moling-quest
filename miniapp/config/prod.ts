import { defineConfig } from '@tarojs/cli'

export default defineConfig({
  mini: {},
  h5: {
    /**
     * 生产环境若部署到二级目录，请改为 '/sub/' 形式
     */
    publicPath: '/'
  }
})
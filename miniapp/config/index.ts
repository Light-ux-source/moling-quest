import { defineConfig } from '@tarojs/cli'
import devConfig from './dev'
import prodConfig from './prod'

export default defineConfig(async (merge) => {
  const outputRoot = process.env.TARO_ENV === 'h5' ? 'dist-h5' : 'dist'
  const baseConfig = {
    projectName: 'learning-with-ai',
    date: '2026-11-09',
    designWidth: 750,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      375: 2,
      828: 1.81 / 2
    },
    sourceRoot: 'src',
    outputRoot,
    plugins: [],
    defineConstants: {
      'process.env.TARO_APP_API_BASE': JSON.stringify(process.env.TARO_APP_API_BASE || '')
    },
    copy: {
      patterns: [{ from: 'src/assets', to: `${outputRoot}/assets` }],
      options: {}
    },
    framework: 'react',
    compiler: 'webpack5',
    cache: {
      enable: false
    },
    mini: {
      postcss: {
        pxtransform: {
          enable: true,
          config: {}
        },
        cssModules: {
          enable: false
        }
      }
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      output: {
        filename: 'js/[name].[hash:8].js',
        chunkFilename: 'js/[name].[chunkhash:8].js'
      },
      miniCssExtractPluginOption: {
        ignoreOrder: true,
        filename: 'css/[name].[hash].css',
        chunkFilename: 'css/[name].[chunkhash].css'
      },
      postcss: {
        autoprefixer: {
          enable: true,
          config: {}
        },
        cssModules: {
          enable: false
        }
      }
    }
  }

  if (process.env.NODE_ENV === 'development') {
    return merge({}, baseConfig, devConfig)
  }
  return merge({}, baseConfig, prodConfig)
})
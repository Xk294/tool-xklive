// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2026-10-21',
  future: {
    compatibilityVersion: 4,
  },
  ssr: false, // SPA Mode cho ứng dụng đồng hành điều khiển thời gian thực
  css: ['~/assets/css/main.css'],
  app: {
    head: {
      title: 'Auto Sound Engineer Companion',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no' },
        { name: 'description', content: 'Ứng dụng đồng hành kiểm soát chống hú và giám sát Behringer XR / Midas MR' },
        { name: 'theme-color', content: '#0b0e14' },
        { name: 'apple-mobile-web-app-capable', content: 'yes' },
        { name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent' }
      ],
      link: [
        { rel: 'manifest', href: '/manifest.json' },
        { rel: 'icon', type: 'image/svg+xml', href: '/icon.svg' }
      ]
    }
  },
  nitro: {
    output: {
      publicDir: './dist'
    }
  }
})

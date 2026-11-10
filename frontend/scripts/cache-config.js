export function shellCacheConfig(dist, revision) {
  return {
    globDirectory: dist, swDest: `${dist}/sw.js`,
    globPatterns: ['assets/**/*.js','assets/**/*.css','icons/**/*.svg','manifest.webmanifest'],
    globIgnores: ['assets/PriceChart-*.js'],
    modifyURLPrefix: {'': '/static/'},
    additionalManifestEntries: [{url: '/offline-shell.html',revision}],
    runtimeCaching: [
      {
        urlPattern: ({url, request, sameOrigin}) => sameOrigin && request.mode === 'navigate' && url.pathname === '/',
        handler: 'NetworkOnly',
        options: {precacheFallback:{fallbackURL:'/offline-shell.html'}},
      },
      {
        urlPattern: ({url, sameOrigin}) => sameOrigin && /^\/static\/assets\/PriceChart-[^/]+\.js$/.test(url.pathname),
        handler: 'CacheFirst',
        options: {cacheName:'gold-etf-chart-v1',expiration:{maxEntries:2}},
      },
    ], cleanupOutdatedCaches: true,
    skipWaiting: false, clientsClaim: true, inlineWorkboxRuntime: true,
    cacheId: 'gold-etf-shell', maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
    sourcemap: false,
  }
}

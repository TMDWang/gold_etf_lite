export function shellCacheConfig(dist, revision) {
  return {
    globDirectory: dist, swDest: `${dist}/sw.js`,
    globPatterns: ['assets/**/*.js','assets/**/*.css','icons/**/*.svg','manifest.webmanifest'],
    modifyURLPrefix: {'': '/static/'},
    additionalManifestEntries: [{url: '/',revision}],
    navigateFallback: '/', navigateFallbackAllowlist: [/^\/$/],
    runtimeCaching: [], cleanupOutdatedCaches: true,
    skipWaiting: false, clientsClaim: true, inlineWorkboxRuntime: true,
    cacheId: 'gold-etf-shell', maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
    sourcemap: false,
  }
}

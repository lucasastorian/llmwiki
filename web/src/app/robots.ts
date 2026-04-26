import type { MetadataRoute } from 'next'

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: ['/api/', '/oauth/', '/callback'],
    },
    sitemap: 'https://llmwiki.app/sitemap.xml',
  }
}

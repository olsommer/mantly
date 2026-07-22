import { mkdir, readFile, writeFile } from "node:fs/promises"
import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { landingMetadata, landingRoutes, type SeoLanguage } from "./seo-metadata"

const PUBLIC_ORIGIN = "https://mantly.io"

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

function replaceRequired(
  html: string,
  pattern: RegExp,
  replacement: string | ((match: string) => string),
  label: string,
) {
  if (!pattern.test(html)) {
    throw new Error(`Cannot generate localized landing HTML: missing ${label}`)
  }
  pattern.lastIndex = 0
  return html.replace(pattern, (match) =>
    typeof replacement === "string" ? replacement : replacement(match),
  )
}

function replaceMetaContent(html: string, attribute: "name" | "property", key: string, content: string) {
  const tagPattern = new RegExp(`<meta\\s+[^>]*${attribute}=["']${key}["'][^>]*>`, "i")
  return replaceRequired(
    html,
    tagPattern,
    (tag) => replaceRequired(
      tag,
      /content=["'][^"']*["']/i,
      `content="${escapeHtml(content)}"`,
      `${key} content`,
    ),
    `${key} meta tag`,
  )
}

function replaceLinkHref(html: string, rel: string, href: string, hreflang?: string) {
  const hreflangPattern = hreflang ? `(?=[^>]*hreflang=["']${hreflang}["'])` : ""
  const tagPattern = new RegExp(`<link\\s+${hreflangPattern}[^>]*rel=["']${rel}["'][^>]*>`, "i")
  return replaceRequired(
    html,
    tagPattern,
    (tag) => replaceRequired(
      tag,
      /href=["'][^"']*["']/i,
      `href="${escapeHtml(href)}"`,
      `${rel}${hreflang ? ` ${hreflang}` : ""} href`,
    ),
    `${rel}${hreflang ? ` ${hreflang}` : ""} link`,
  )
}

function renderLocalizedHomeHtml(source: string, language: SeoLanguage) {
  const pageMetadata = landingMetadata[language].home
  const canonicalUrl = `${PUBLIC_ORIGIN}${landingRoutes.home[language]}`
  const englishUrl = `${PUBLIC_ORIGIN}${landingRoutes.home.en}`
  const germanUrl = `${PUBLIC_ORIGIN}${landingRoutes.home.de}`

  let html = replaceRequired(
    source,
    /<html\b[^>]*>/i,
    (tag) => /\slang=["'][^"']*["']/i.test(tag)
      ? tag.replace(/\slang=["'][^"']*["']/i, ` lang="${language}"`)
      : tag.replace("<html", `<html lang="${language}"`),
    "html element",
  )
  html = replaceRequired(
    html,
    /<title>[\s\S]*?<\/title>/i,
    `<title>${escapeHtml(pageMetadata.title)}</title>`,
    "title",
  )
  html = replaceMetaContent(html, "name", "description", pageMetadata.description)
  html = replaceMetaContent(html, "property", "og:title", pageMetadata.title)
  html = replaceMetaContent(html, "property", "og:description", pageMetadata.description)
  html = replaceMetaContent(html, "property", "og:url", canonicalUrl)
  html = replaceMetaContent(html, "property", "og:locale", language === "de" ? "de_DE" : "en_US")
  html = replaceMetaContent(html, "name", "twitter:title", pageMetadata.title)
  html = replaceMetaContent(html, "name", "twitter:description", pageMetadata.description)
  html = replaceLinkHref(html, "canonical", canonicalUrl)
  html = replaceLinkHref(html, "alternate", englishUrl, "en")
  html = replaceLinkHref(html, "alternate", germanUrl, "de")
  html = replaceLinkHref(html, "alternate", `${PUBLIC_ORIGIN}/`, "x-default")
  return html
}

function localizedStaticHtml(): Plugin {
  let outputDirectory = ""

  return {
    name: "mantly-localized-static-html",
    apply: "build",
    configResolved(config) {
      outputDirectory = path.resolve(config.root, config.build.outDir)
    },
    async closeBundle() {
      const rootIndexPath = path.join(outputDirectory, "index.html")
      const source = await readFile(rootIndexPath, "utf8")
      const englishHtml = renderLocalizedHomeHtml(source, "en")
      const germanHtml = renderLocalizedHomeHtml(source, "de")
      const englishDirectory = path.join(outputDirectory, "en")
      const germanDirectory = path.join(outputDirectory, "de")

      await Promise.all([
        mkdir(englishDirectory, { recursive: true }),
        mkdir(germanDirectory, { recursive: true }),
      ])
      await Promise.all([
        writeFile(rootIndexPath, englishHtml, "utf8"),
        writeFile(path.join(englishDirectory, "index.html"), englishHtml, "utf8"),
        writeFile(path.join(germanDirectory, "index.html"), germanHtml, "utf8"),
      ])
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
    tailwindcss(),
    localizedStaticHtml(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@demo": path.resolve(__dirname, "../demo"),
    },
  },
})

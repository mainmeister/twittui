<?xml version="1.0" encoding="utf-8"?>
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
    xmlns:content="http://purl.org/rss/1.0/modules/content/"
    xmlns:atom="http://www.w3.org/2005/Atom">

  <xsl:output method="html" encoding="utf-8" indent="yes" doctype-public="-//W3C//DTD HTML 4.01 Transitional//EN" doctype-system="http://www.w3.org/TR/html4/loose.dtd" />

  <xsl:template match="/">
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title><xsl:value-of select="/rss/channel/title" /> - RSS Feed</title>
        <style>
          :root {
            --primary: #0366d6;
            --primary-hover: #024ea4;
            --bg-page: #f6f8fa;
            --bg-card: #ffffff;
            --text-main: #24292e;
            --text-muted: #586069;
            --border-color: #e1e4e8;
            --badge-bg: #eef2f8;
            --badge-text: #0366d6;
          }

          * {
            box-sizing: border-box;
          }

          body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
            line-height: 1.6;
          }

          .container {
            max-width: 920px;
            margin: 0 auto;
            background: var(--bg-card);
            border-radius: 8px;
            padding: 32px;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
          }

          .notice-banner {
            background-color: #fffbdd;
            border: 1px solid #f9e2ae;
            border-radius: 6px;
            padding: 12px 16px;
            margin-bottom: 24px;
            font-size: 0.9em;
            color: #735c0f;
          }

          .notice-banner strong {
            color: #533f03;
          }

          .header {
            display: flex;
            flex-direction: row;
            gap: 24px;
            align-items: flex-start;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 24px;
            margin-bottom: 28px;
          }

          .channel-image {
            width: 120px;
            height: 120px;
            border-radius: 8px;
            object-fit: cover;
            border: 1px solid var(--border-color);
            flex-shrink: 0;
          }

          .header-info {
            flex: 1;
          }

          .header-info h1 {
            margin: 0 0 8px 0;
            color: var(--primary);
            font-size: 1.8em;
          }

          .header-info .channel-desc {
            color: var(--text-muted);
            margin: 0 0 12px 0;
            font-size: 1em;
          }

          .header-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            font-size: 0.85em;
            color: var(--text-muted);
          }

          .header-meta span {
            background: var(--badge-bg);
            color: var(--badge-text);
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 500;
          }

          .episodes-heading {
            font-size: 1.3em;
            margin: 0 0 16px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
          }

          .episode-card {
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 18px;
            background-color: var(--bg-card);
            transition: box-shadow 0.2s ease, border-color 0.2s ease;
          }

          .episode-card:hover {
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
            border-color: #c8d1dc;
          }

          .episode-title {
            margin: 0 0 8px 0;
            font-size: 1.2em;
          }

          .episode-title a {
            color: var(--text-main);
            text-decoration: none;
          }

          .episode-title a:hover {
            color: var(--primary);
            text-decoration: underline;
          }

          .episode-meta {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 12px;
            font-size: 0.85em;
            color: var(--text-muted);
            margin-bottom: 12px;
          }

          .episode-description {
            color: #3f444e;
            font-size: 0.95em;
            margin-bottom: 16px;
            word-break: break-word;
          }

          .episode-description p {
            margin: 0 0 8px 0;
          }

          .episode-description p:last-child {
            margin-bottom: 0;
          }

          .media-controls {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 12px;
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px dashed var(--border-color);
          }

          .media-link {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background-color: var(--primary);
            color: #ffffff;
            padding: 7px 16px;
            border-radius: 4px;
            font-size: 0.9em;
            text-decoration: none;
            font-weight: 500;
            transition: background-color 0.15s ease;
          }

          .media-link:hover {
            background-color: var(--primary-hover);
            color: #ffffff;
          }

          .media-type {
            font-size: 0.8em;
            color: var(--text-muted);
          }

          @media (max-width: 600px) {
            body {
              padding: 12px;
            }
            .container {
              padding: 18px;
            }
            .header {
              flex-direction: column;
              align-items: center;
              text-align: center;
            }
            .channel-image {
              width: 96px;
              height: 96px;
            }
          }
        </style>
      </head>
      <body>
        <div class="container">
          <div class="notice-banner">
            <strong>Podcast RSS Feed View:</strong> This page is formatted via an XSLT stylesheet (<code>feed-style.xsl</code>). You can subscribe to this podcast by copying this URL into your podcast client.
          </div>

          <div class="header">
            <xsl:if test="/rss/channel/itunes:image/@href">
              <img class="channel-image" src="{/rss/channel/itunes:image/@href}" alt="Podcast Cover Art" />
            </xsl:if>
            <xsl:if test="not(/rss/channel/itunes:image/@href) and /rss/channel/image/url">
              <img class="channel-image" src="{/rss/channel/image/url}" alt="Podcast Cover Art" />
            </xsl:if>

            <div class="header-info">
              <h1><xsl:value-of select="/rss/channel/title" /></h1>
              <p class="channel-desc"><xsl:value-of select="/rss/channel/description" /></p>

              <div class="header-meta">
                <xsl:if test="/rss/channel/link">
                  <a href="{/rss/channel/link}" target="_blank" rel="noopener noreferrer">Visit Website</a>
                </xsl:if>
                <xsl:if test="/rss/channel/itunes:author">
                  <span>Author: <xsl:value-of select="/rss/channel/itunes:author" /></span>
                </xsl:if>
                <xsl:if test="/rss/channel/language">
                  <span>Language: <xsl:value-of select="/rss/channel/language" /></span>
                </xsl:if>
              </div>
            </div>
          </div>

          <div class="episodes-heading">
            Episodes (<xsl:value-of select="count(/rss/channel/item)" />)
          </div>

          <div class="episodes-list">
            <xsl:for-each select="/rss/channel/item">
              <div class="episode-card">
                <h2 class="episode-title">
                  <xsl:choose>
                    <xsl:when test="link and link != ''">
                      <a href="{link}" target="_blank" rel="noopener noreferrer">
                        <xsl:value-of select="title" />
                      </a>
                    </xsl:when>
                    <xsl:otherwise>
                      <xsl:value-of select="title" />
                    </xsl:otherwise>
                  </xsl:choose>
                </h2>

                <div class="episode-meta">
                  <xsl:if test="pubDate">
                    <span>Published: <xsl:value-of select="pubDate" /></span>
                  </xsl:if>
                  <xsl:if test="itunes:duration">
                    <span>Duration: <xsl:value-of select="itunes:duration" /></span>
                  </xsl:if>
                  <xsl:if test="itunes:episode">
                    <span>Episode #<xsl:value-of select="itunes:episode" /></span>
                  </xsl:if>
                </div>

                <div class="episode-description">
                  <xsl:choose>
                    <xsl:when test="content:encoded and content:encoded != ''">
                      <xsl:value-of select="content:encoded" disable-output-escaping="yes" />
                    </xsl:when>
                    <xsl:when test="description and description != ''">
                      <xsl:value-of select="description" disable-output-escaping="yes" />
                    </xsl:when>
                    <xsl:when test="itunes:summary and itunes:summary != ''">
                      <xsl:value-of select="itunes:summary" />
                    </xsl:when>
                  </xsl:choose>
                </div>

                <xsl:if test="enclosure/@url">
                  <div class="media-controls">
                    <a class="media-link" href="{enclosure/@url}" target="_blank" rel="noopener noreferrer">
                      &#9654; Stream / Download Media
                    </a>
                    <span class="media-type">
                      <xsl:value-of select="enclosure/@type" />
                      <xsl:if test="enclosure/@length and enclosure/@length != '0'">
                        &#160;&#8226;&#160;<xsl:value-of select="round(enclosure/@length div 1048576)" /> MB
                      </xsl:if>
                    </span>
                  </div>
                </xsl:if>
              </div>
            </xsl:for-each>
          </div>
        </div>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>

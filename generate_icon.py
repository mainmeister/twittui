"""TwitTUI Icon Generator.

Generates high-resolution PNGs, multi-resolution ICO, and scalable SVG assets
for TwitTUI (TWiT.tv Terminal & Desktop Media Browser).
"""

import os
import math
import cairo
import gi

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf  # noqa: E402


def generate_svg(output_path: str) -> None:
    """Generate scalable vector graphic (SVG) for the TwitTUI icon."""
    svg_content = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <!-- Outer background gradient -->
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#1e202c"/>
      <stop offset="100%" stop-color="#101118"/>
    </linearGradient>

    <!-- Outer glowing rim gradient -->
    <linearGradient id="rimGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ff3b30"/>
      <stop offset="50%" stop-color="#9c27b0"/>
      <stop offset="100%" stop-color="#00e5ff"/>
    </linearGradient>

    <!-- Inner CRT/Terminal screen gradient -->
    <linearGradient id="screenGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#0d0e14"/>
      <stop offset="100%" stop-color="#050608"/>
    </linearGradient>

    <!-- Central Play / Stream gradient -->
    <linearGradient id="playGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ff5722"/>
      <stop offset="100%" stop-color="#d32f2f"/>
    </linearGradient>

    <!-- Drop shadow filter -->
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#000000" flood-opacity="0.6"/>
    </filter>
  </defs>

  <!-- Base Squircle Tile -->
  <rect x="20" y="20" width="472" height="472" rx="105" ry="105" fill="url(#bgGrad)" filter="url(#shadow)"/>
  <rect x="20" y="20" width="472" height="472" rx="105" ry="105" fill="none" stroke="url(#rimGrad)" stroke-width="10"/>

  <!-- Inner Terminal CRT Screen -->
  <rect x="62" y="66" width="388" height="380" rx="50" ry="50" fill="url(#screenGrad)" stroke="#2b3044" stroke-width="6"/>

  <!-- Terminal Window Controls (Traffic Lights) -->
  <circle cx="102" cy="100" r="9" fill="#ff5f56"/>
  <circle cx="132" cy="100" r="9" fill="#ffbd2e"/>
  <circle cx="162" cy="100" r="9" fill="#27c93f"/>

  <!-- Title Pill / Mini Header Bar -->
  <rect x="190" y="94" width="225" height="12" rx="6" fill="#3b4259" opacity="0.6"/>

  <!-- Broadcast Podcast / Media Signal Waves -->
  <!-- Left Outer Wave -->
  <path d="M 175 220 A 130 130 0 0 1 205 170" fill="none" stroke="#ff3b30" stroke-width="12" stroke-linecap="round" opacity="0.5"/>
  <!-- Left Middle Wave -->
  <path d="M 195 240 A 90 90 0 0 1 220 200" fill="none" stroke="#ff5252" stroke-width="11" stroke-linecap="round" opacity="0.75"/>
  <!-- Left Inner Wave -->
  <path d="M 215 255 A 55 55 0 0 1 232 230" fill="none" stroke="#ff7961" stroke-width="10" stroke-linecap="round" opacity="0.95"/>

  <!-- Right Outer Wave -->
  <path d="M 337 170 A 130 130 0 0 1 307 220" fill="none" stroke="#ff3b30" stroke-width="12" stroke-linecap="round" opacity="0.5"/>
  <!-- Right Middle Wave -->
  <path d="M 317 200 A 90 90 0 0 1 292 240" fill="none" stroke="#ff5252" stroke-width="11" stroke-linecap="round" opacity="0.75"/>
  <!-- Right Inner Wave -->
  <path d="M 297 230 A 55 55 0 0 1 280 255" fill="none" stroke="#ff7961" stroke-width="10" stroke-linecap="round" opacity="0.95"/>

  <!-- Central TWiT Media Play Button -->
  <polygon points="190,185 348,272 190,359" fill="url(#playGrad)" stroke="#ff8a80" stroke-width="5" stroke-linejoin="round"/>

  <!-- Glowing Terminal Prompt Chevron ( > ) -->
  <path d="M 148 226 L 198 272 L 148 318" fill="none" stroke="#00e5ff" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>

  <!-- Glowing Terminal Blinking Cursor Block ( _ ) -->
  <rect x="260" y="342" width="90" height="20" rx="4" fill="#00e5ff" opacity="0.95"/>
</svg>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_content.strip() + "\n")


def render_icon_surface(size: int) -> cairo.ImageSurface:
    """Render high quality icon surface with Cairo at arbitrary dimension."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    ctx.scale(size, size)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)

    # Outer squircle / rounded tile
    pad = 0.04
    r = 0.22
    x0, y0, w, h = pad, pad, 1.0 - 2 * pad, 1.0 - 2 * pad

    # Outer base shadow / background
    bg_gradient = cairo.LinearGradient(0, 0, 0, 1)
    bg_gradient.add_color_stop_rgb(0.0, 0.11, 0.12, 0.16)  # Deep midnight slate
    bg_gradient.add_color_stop_rgb(1.0, 0.06, 0.07, 0.09)  # Dark charcoal

    ctx.new_sub_path()
    ctx.arc(x0 + w - r, y0 + r, r, -math.pi / 2, 0)
    ctx.arc(x0 + w - r, y0 + h - r, r, 0, math.pi / 2)
    ctx.arc(x0 + r, y0 + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()

    ctx.set_source(bg_gradient)
    ctx.fill_preserve()

    # Outer Rim Highlight (TWiT Red to Terminal Cyan)
    rim_gradient = cairo.LinearGradient(0, 0, 1, 1)
    rim_gradient.add_color_stop_rgba(0.0, 0.95, 0.28, 0.20, 0.9)  # TWiT Red
    rim_gradient.add_color_stop_rgba(0.5, 0.50, 0.30, 0.85, 0.8)  # Purple bridge
    rim_gradient.add_color_stop_rgba(1.0, 0.00, 0.85, 0.75, 0.9)  # Neon Cyan
    ctx.set_source(rim_gradient)
    ctx.set_line_width(0.022)
    ctx.stroke()

    # Terminal Display Screen (Inset CRT Window)
    t_pad_x = 0.12
    t_pad_y = 0.13
    t_r = 0.10
    tx0, ty0 = t_pad_x, t_pad_y
    tw, th = 1.0 - 2 * t_pad_x, 1.0 - 2 * t_pad_y

    ctx.new_sub_path()
    ctx.arc(tx0 + tw - t_r, ty0 + t_r, t_r, -math.pi / 2, 0)
    ctx.arc(tx0 + tw - t_r, ty0 + th - t_r, t_r, 0, math.pi / 2)
    ctx.arc(tx0 + t_r, ty0 + th - t_r, t_r, math.pi / 2, math.pi)
    ctx.arc(tx0 + t_r, ty0 + t_r, t_r, math.pi, 3 * math.pi / 2)
    ctx.close_path()

    t_gradient = cairo.LinearGradient(0, ty0, 0, ty0 + th)
    t_gradient.add_color_stop_rgb(0.0, 0.05, 0.06, 0.08)  # Terminal black
    t_gradient.add_color_stop_rgb(1.0, 0.02, 0.02, 0.04)  # Deep pitch
    ctx.set_source(t_gradient)
    ctx.fill_preserve()

    ctx.set_source_rgba(0.18, 0.22, 0.30, 0.8)
    ctx.set_line_width(0.012)
    ctx.stroke()

    # Terminal Window Controls: Traffic lights
    dot_y = ty0 + 0.065
    dot_r = 0.018
    dots = [
        (tx0 + 0.065, (0.95, 0.35, 0.35)),  # Red
        (tx0 + 0.125, (0.95, 0.75, 0.25)),  # Amber
        (tx0 + 0.185, (0.25, 0.85, 0.45)),  # Green
    ]
    for dx, (dr, dg, db) in dots:
        ctx.arc(dx, dot_y, dot_r, 0, 2 * math.pi)
        ctx.set_source_rgb(dr, dg, db)
        ctx.fill()

    # Title header bar placeholder
    ctx.save()
    ctx.set_source_rgba(0.5, 0.6, 0.7, 0.4)
    ctx.rectangle(tx0 + 0.24, dot_y - 0.015, tw - 0.30, 0.03)
    ctx.fill()
    ctx.restore()

    # Broadcast / Podcast Signal Waves
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    center_x = 0.50
    signal_origin_y = 0.52

    waves = [
        (0.24, 0.50, 0.024),
        (0.34, 0.75, 0.026),
        (0.44, 0.95, 0.028),
    ]
    for radius, alpha, l_width in waves:
        ctx.set_line_width(l_width)
        ctx.set_source_rgba(1.0, 0.32, 0.22, alpha)
        ctx.arc(center_x, signal_origin_y, radius, -math.pi * 0.80, -math.pi * 0.62)
        ctx.stroke()
        ctx.set_source_rgba(1.0, 0.32, 0.22, alpha)
        ctx.arc(center_x, signal_origin_y, radius, -math.pi * 0.38, -math.pi * 0.20)
        ctx.stroke()
    ctx.restore()

    # Central Media Play Triangle
    ctx.save()
    play_grad = cairo.LinearGradient(0.34, 0.35, 0.72, 0.65)
    play_grad.add_color_stop_rgb(0.0, 1.0, 0.36, 0.22)
    play_grad.add_color_stop_rgb(1.0, 0.85, 0.12, 0.10)
    ctx.set_source(play_grad)

    px1, py1 = 0.36, 0.35
    px2, py2 = 0.68, 0.53
    px3, py3 = 0.36, 0.71

    ctx.move_to(px1, py1)
    ctx.line_to(px2, py2)
    ctx.line_to(px3, py3)
    ctx.close_path()
    ctx.fill_preserve()

    ctx.set_source_rgba(1.0, 0.8, 0.7, 0.6)
    ctx.set_line_width(0.012)
    ctx.stroke()
    ctx.restore()

    # Terminal Prompt & Cyber Cursor Overlay
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)

    # Prompt Chevron '>'
    ctx.set_source_rgba(0.0, 0.95, 0.80, 1.0)
    ctx.set_line_width(0.040)
    ctx.move_to(0.28, 0.44)
    ctx.line_to(0.38, 0.53)
    ctx.line_to(0.28, 0.62)
    ctx.stroke()

    # Terminal Cursor Block '_'
    ctx.set_source_rgba(0.0, 0.95, 0.80, 0.95)
    ctx.rectangle(0.50, 0.66, 0.18, 0.042)
    ctx.fill()
    ctx.restore()

    return surface


def generate_all_icons(resources_dir: str) -> list[str]:
    """Generate all icon formats and sized variants in target directory."""
    os.makedirs(resources_dir, exist_ok=True)
    generated = []

    # 1. Scalable vector graphic (SVG)
    svg_path = os.path.join(resources_dir, "twittui.svg")
    generate_svg(svg_path)
    generated.append(svg_path)

    # 2. Sized PNG files (Toga supported sizes)
    sizes = [512, 256, 128, 72, 64, 48, 32, 16]
    for s in sizes:
        surf = render_icon_surface(s)
        file_path = os.path.join(resources_dir, f"twittui-{s}.png")
        surf.write_to_png(file_path)
        generated.append(file_path)

    # 3. Default master twittui.png
    master_png = os.path.join(resources_dir, "twittui.png")
    render_icon_surface(512).write_to_png(master_png)
    generated.append(master_png)

    # 4. Windows ICO file
    ico_path = os.path.join(resources_dir, "twittui.ico")
    pixbuf_256 = GdkPixbuf.Pixbuf.new_from_file(os.path.join(resources_dir, "twittui-256.png"))
    pixbuf_256.savev(ico_path, "ico", [], [])
    generated.append(ico_path)

    return generated


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    res_dir = os.path.join(base_dir, "resources")
    files = generate_all_icons(res_dir)
    print(f"Generated {len(files)} icon assets in '{res_dir}':")
    for f in files:
        print(f" - {os.path.basename(f)}")

---
name: animation-video
description: Create, render, and validate code-driven animation videos such as motion graphics, explainers, animated text, shape systems, UI mockups, data visualizations, and MP4/GIF/WebM outputs. Use when Codex needs to turn a written idea into a local video artifact using Remotion, HTML/CSS/Playwright capture, Pillow frame generation, or adjacent deterministic animation tools.
---

# Animation Video

## Workflow

Use deterministic code-rendered animation when the user needs crisp text, exact layout, UI screens, diagrams, charts, or brand-safe motion. Prefer generative video models only for photorealistic footage or cinematic live-action scenes.

1. Choose the renderer:
   - **Remotion** for React-based motion graphics, composited scenes, charts, text animation, captions, and reusable video components.
   - **HTML/CSS + Playwright capture** for single-file UI/chat/product mockups where exact typography and browser layout matter.
   - **Pillow/Manim** for frame-by-frame drawing, math/technical explainers, or when Node/Remotion is unavailable.
2. Make a short storyboard: duration, resolution, fps, scene beats, key text, palette, and final deliverable.
3. Render a still frame before the final video when layout risk is nontrivial.
4. Render MP4 with H.264 and `yuv420p`-compatible output when possible.
5. Validate the video artifact with `scripts/verify_video.py`, and inspect at least one representative still.

## Remotion

Use the installed `remotion-best-practices` skill when writing Remotion code.

For a new local project:

```powershell
npx create-video@latest --yes --blank --no-tailwind my-video
cd my-video
npm install
```

Write animation with `useCurrentFrame()`, `useVideoConfig()`, `interpolate()`, `spring()`, `Sequence`, and `AbsoluteFill`. Do not use CSS animations or CSS transitions for frame-critical motion; Remotion renders deterministic frames from React state.

Typical checks:

```powershell
npm run lint
npx remotion still src/index.ts MyComp out/frame-75.png --frame=75
npx remotion render src/index.ts MyComp out/video.mp4 --codec=h264 --crf=18
python C:/Users/me/.agents/skills/animation-video/scripts/verify_video.py out/video.mp4 --min-size 100000 --expect-duration 5
```

## HTML Capture

Use this path for a single HTML file that animates text, cards, chat bubbles, SVG lines, or dashboards. Keep viewport constants explicit and match `body` dimensions. Drive timing with JavaScript and `requestAnimationFrame`; capture via Playwright, then transcode to MP4 if FFmpeg is available.

## Validation

Always validate:

- The output file exists and is not tiny.
- The container is recognizable as MP4 (`ftyp`, `moov`, and `mdat` boxes).
- Duration roughly matches the storyboard.
- A still frame is nonblank and representative.
- Text fits inside its containers at the target resolution.

Use `references/research-summary.md` for the 2026 capability notes and source trail.

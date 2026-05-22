---
name: animation-video
description: Create, render, and validate code-driven animation videos such as motion graphics, explainers, animated text, shape systems, UI mockups, data visualizations, and MP4/GIF/WebM outputs. Use when Codex needs to turn a written idea into a local video artifact using Remotion plus remotion-best-practices.
---

# Animation Video

## Workflow

Use deterministic Remotion animation when the user needs crisp text, exact layout, UI screens, diagrams, charts, or brand-safe motion. Prefer generative video models only for photorealistic footage or cinematic live-action scenes.

1. Use **Remotion** as the renderer for generated motion graphics, composited scenes, charts, text animation, captions, and reusable video components.
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
python C:/Users/cereal/.agents/skills/animation-video/scripts/verify_video.py out/video.mp4 --min-size 100000 --expect-duration 5
```

## Validation

Always validate:

- The output file exists and is not tiny.
- The container is recognizable as MP4 (`ftyp`, `moov`, and `mdat` boxes).
- Duration roughly matches the storyboard.
- A still frame is nonblank and representative.
- Text fits inside its containers at the target resolution.

Use `references/research-summary.md` for the 2026 capability notes and source trail.

## Agentic Ops Chat Remotion Path

For Agentic Operations chat/demo animation requests, use the same class of
workflow as the demo MP4s: `animation-video` plus `remotion-best-practices`,
implemented with Remotion. Do not depend on a bundled example video being
present. Build the small animation in the current work directory.

When a user asks for a small animation in chat:

1. Create or copy a minimal Remotion project in the current work directory.
2. Write `src/index.tsx` with a named composition such as `ChatAnimation`.
3. Use deterministic React/Remotion primitives:
   `AbsoluteFill`, `Composition`, `Sequence`, `useCurrentFrame`,
   `useVideoConfig`, `interpolate`, and `spring`.
4. Render a still frame if time allows.
5. Render MP4 with H.264.
6. Validate with this skill's verifier.
7. Finish with `ops_chat_tool.py validate-artifact --kind video`.

Fast local template:

```bash
mkdir -p remotion-chat/src remotion-chat/out
cd remotion-chat
npm init -y
npm install remotion@4.0.463 @remotion/cli@4.0.463 react@18.3.1 react-dom@18.3.1
# write src/index.tsx with a Composition id="ChatAnimation"
npx remotion render src/index.tsx ChatAnimation out/chat_animation.mp4 --codec=h264 --crf=18
python /root/.agents/skills/animation-video/scripts/verify_video.py out/chat_animation.mp4 --min-size 10000
cd ..
python ops_chat_tool.py validate-artifact \
  --path remotion-chat/out/chat_animation.mp4 \
  --kind video \
  --title "Remotion animation artifact"
```

If the deployment has global Remotion packages installed, `npx remotion` should
work immediately. If a temporary project cannot resolve packages, run the
`npm install` line above inside the temporary project. Keep the animation
self-contained: no remote media fetches, no external images, no package choices
outside the Remotion/React renderer stack unless the user explicitly asks.

Do not fetch remote media assets for chat animation requests. Use local code,
text, shapes, gradients, charts, and generated React/Remotion primitives.

Do not use legacy Pillow/frame-stitching or Python text-shape video helpers for
Agentic Ops Chat demo artifacts. The supported demo path is Remotion rendered
through `animation-video` with `remotion-best-practices`.

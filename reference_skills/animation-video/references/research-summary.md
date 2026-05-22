# 2026 Research Summary

- Remotion officially documents prompting videos with coding agents such as Claude Code, Codex, and OpenCode. Their recommended flow is `npx create-video@latest`, choose a blank project, install skills, preview with `npm run dev`, and render via Remotion.
- Remotion's agent skill package is installed with `npx skills add remotion-dev/skills`; in this environment it installed globally for Codex as `C:\Users\me\.agents\skills\remotion-best-practices`.
- The Remotion skill teaches agent-side rules: use React components, `useCurrentFrame()`, `interpolate()`, `spring()`, `Sequence`, explicit composition dimensions/duration/fps, and avoid CSS animations for render-critical motion.
- Adjacent 2026 approaches include HTML-to-MP4 capture for crisp text/UI, Pillow/FFmpeg frame generation for simple motion graphics, and larger Claude Code video toolkits combining Remotion, FFmpeg, browser recording, voiceover, and scene review.
- Practical rule for Agentic Operations: use Remotion for polished text-and-shape videos, animated diagrams, charts, and UI-style motion. The older Python/text-shapes helpers have been removed from this skill so chat/demo agents do not fall back to the wrong renderer.

Sources consulted in this session:

- https://www.remotion.dev/docs/ai/claude-code
- https://www.remotion.dev/docs/ai/skills
- https://github.com/remotion-dev/skills
- https://github.com/digitalsamba/claude-code-video-toolkit
- https://github.com/Universaljojo/html-to-mp4
- https://github.com/aryankumar06/claude-code-skills

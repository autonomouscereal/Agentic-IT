# Agentic Ops Demo Videos

Short 1080p MP4 motion diagrams for the demo v4 opening and intake sequence.

## Rendered Clips

| File | Duration | Use |
|---|---:|---|
| `out/01_problem_current_model.mp4` | 12s | Show why current automation rearranges work instead of removing it. |
| `out/02_solution_control_plane.mp4` | 12s | Show the governed agentic operations layer above intake sources and tools. |
| `out/03_intake_magic_flow.mp4` | 13s | Lead directly into the intake demo with the Teams-style lockout request. |
| `out/04_modular_adoption_path.mp4` | 12s | Use later when explaining start-small deployment and modular adoption. |
| `out/demo_v4_problem_solution_sequence.mp4` | 49s | Continuous opening sequence combining all four diagrams. |

## Suggested Talk Track

1. Play `01_problem_current_model.mp4` while saying:
   "Most automation projects do not remove the work. They rearrange it across
   more tools, dashboards, teams, and handoffs."
2. Play `02_solution_control_plane.mp4` while saying:
   "The product is the governed layer above the tools: classify, route, assign
   agents, enforce approvals, broker access, and record evidence."
3. Play `03_intake_magic_flow.mp4` immediately before the live intake demo:
   "The user sees a simple conversation. The business gets structured work,
   governed execution, and audit evidence."
4. Save `04_modular_adoption_path.mp4` for the setup section:
   "Customers can start small and add modules only when they are ready."

## Re-render

```powershell
cd "D:\IT AGENT PROJECT\demo_assets\agentic_ops_videos"
npm install
npx remotion render src/index.tsx DemoV4Sequence out/demo_v4_problem_solution_sequence.mp4 --codec=h264 --crf=18
```

Individual compositions:

- `ProblemState`
- `SolutionLayer`
- `IntakeFlow`
- `AdoptionPath`
- `DemoV4Sequence`

import React from "react";
import {
  AbsoluteFill,
  Composition,
  Easing,
  interpolate,
  random,
  registerRoot,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const palette = {
  bg: "#07111f",
  panel: "#0e1b2d",
  panel2: "#13243a",
  line: "#334760",
  text: "#eef6ff",
  muted: "#8ea4bd",
  cyan: "#54d6ff",
  green: "#4ade80",
  amber: "#fbbf24",
  red: "#fb7185",
  purple: "#a78bfa",
};

const font = "Segoe UI, Inter, Arial, sans-serif";
const fps = 30;

const ease = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

const fade = (frame: number, start: number, end: number) => ease(frame, start, end);

const rise = (frame: number, start: number, end: number, distance = 18) => ({
  opacity: fade(frame, start, end),
  transform: `translateY(${interpolate(frame, [start, end], [distance, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  })}px)`,
});

const Shell: React.FC<{ title: string; kicker: string; children: React.ReactNode }> = ({
  title,
  kicker,
  children,
}) => (
  <AbsoluteFill
    style={{
      background:
        "radial-gradient(circle at 12% 12%, rgba(84,214,255,0.13), transparent 24%), radial-gradient(circle at 88% 18%, rgba(167,139,250,0.11), transparent 23%), #07111f",
      color: palette.text,
      fontFamily: font,
      overflow: "hidden",
    }}
  >
    <div
      style={{
        position: "absolute",
        top: 48,
        left: 70,
        right: 70,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <div>
        <div style={{ color: palette.cyan, fontSize: 21, fontWeight: 800, letterSpacing: 0 }}>
          {kicker}
        </div>
        <div style={{ fontSize: 44, fontWeight: 850, letterSpacing: 0, marginTop: 6 }}>{title}</div>
      </div>
      <div
        style={{
          border: `1px solid ${palette.line}`,
          borderRadius: 10,
          padding: "10px 14px",
          color: palette.muted,
          fontSize: 17,
          background: "rgba(10, 20, 34, 0.78)",
        }}
      >
        Agentic Operations
      </div>
    </div>
    {children}
  </AbsoluteFill>
);

const Card: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub?: string;
  color?: string;
  delay?: number;
  icon?: string;
}> = ({ x, y, w, h, label, sub, color = palette.cyan, delay = 0, icon }) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        borderRadius: 12,
        border: `1px solid ${color}77`,
        background: "linear-gradient(180deg, rgba(19,36,58,0.95), rgba(10,19,32,0.96))",
        boxShadow: `0 0 28px ${color}22`,
        padding: 18,
        boxSizing: "border-box",
        ...rise(frame, delay, delay + 14),
      }}
    >
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        {icon ? <div style={{ fontSize: 28 }}>{icon}</div> : null}
        <div style={{ color, fontSize: 18, fontWeight: 800 }}>{label}</div>
      </div>
      {sub ? <div style={{ color: palette.muted, fontSize: 15, lineHeight: 1.28, marginTop: 8 }}>{sub}</div> : null}
    </div>
  );
};

const Label: React.FC<{
  x: number;
  y: number;
  text: string;
  size?: number;
  color?: string;
  delay?: number;
  weight?: number;
  width?: number;
}> = ({ x, y, text, size = 28, color = palette.text, delay = 0, weight = 800, width }) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        fontSize: size,
        color,
        fontWeight: weight,
        lineHeight: 1.14,
        letterSpacing: 0,
        ...rise(frame, delay, delay + 16),
      }}
    >
      {text}
    </div>
  );
};

const Line: React.FC<{
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color?: string;
  delay?: number;
  dashed?: boolean;
  width?: number;
}> = ({ x1, y1, x2, y2, color = palette.cyan, delay = 0, dashed = false, width = 3 }) => {
  const frame = useCurrentFrame();
  const progress = ease(frame, delay, delay + 24);
  const ax2 = x1 + (x2 - x1) * progress;
  const ay2 = y1 + (y2 - y1) * progress;
  return (
    <svg style={{ position: "absolute", inset: 0, overflow: "visible" }}>
      <defs>
        <marker id={`arrow-${color.replace("#", "")}-${delay}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
        </marker>
      </defs>
      <line
        x1={x1}
        y1={y1}
        x2={ax2}
        y2={ay2}
        stroke={color}
        strokeWidth={width}
        strokeLinecap="round"
        strokeDasharray={dashed ? "10 10" : undefined}
        markerEnd={progress > 0.96 ? `url(#arrow-${color.replace("#", "")}-${delay})` : undefined}
        opacity={0.9}
      />
    </svg>
  );
};

const PulseDot: React.FC<{ x: number; y: number; color?: string; delay?: number; label?: string }> = ({
  x,
  y,
  color = palette.cyan,
  delay = 0,
  label,
}) => {
  const frame = useCurrentFrame();
  const t = Math.max(0, frame - delay);
  const scale = 1 + (Math.sin(t / 8) + 1) * 0.16;
  const opacity = fade(frame, delay, delay + 12);
  return (
    <div style={{ position: "absolute", left: x, top: y, opacity }}>
      <div
        style={{
          width: 18,
          height: 18,
          borderRadius: 999,
          background: color,
          boxShadow: `0 0 20px ${color}`,
          transform: `scale(${scale})`,
        }}
      />
      {label ? (
        <div style={{ color: palette.muted, fontSize: 13, marginTop: 6, transform: "translateX(-35%)", whiteSpace: "nowrap" }}>
          {label}
        </div>
      ) : null}
    </div>
  );
};

const ProblemState: React.FC = () => {
  const frame = useCurrentFrame();
  const backlog = Math.floor(interpolate(frame, [80, 300], [2, 18], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  return (
    <Shell title="The Current Model Rearranges Work" kicker="Problem">
      <Label x={88} y={150} text="Work starts everywhere" size={25} color={palette.muted} delay={10} />
      <Card x={74} y={205} w={250} h={86} label="User requests" sub="chat, email, portal" icon="💬" delay={20} />
      <Card x={74} y={313} w={250} h={86} label="Alerts" sub="SIEM, EDR, monitoring" icon="⚠️" delay={28} color={palette.amber} />
      <Card x={74} y={421} w={250} h={86} label="CI/CD failures" sub="scans, builds, deploys" icon="⛔" delay={36} color={palette.red} />
      <Card x={74} y={529} w={250} h={86} label="Tickets" sub="ITSM queues" icon="🎫" delay={44} color={palette.purple} />

      <Line x1={324} y1={248} x2={575} y2={340} delay={58} color={palette.muted} dashed />
      <Line x1={324} y1={356} x2={575} y2={374} delay={62} color={palette.muted} dashed />
      <Line x1={324} y1={464} x2={575} y2={408} delay={66} color={palette.muted} dashed />
      <Line x1={324} y1={572} x2={575} y2={442} delay={70} color={palette.muted} dashed />

      <div
        style={{
          position: "absolute",
          left: 565,
          top: 272,
          width: 300,
          height: 230,
          borderRadius: 18,
          background: "linear-gradient(180deg, rgba(251,113,133,0.16), rgba(14,27,45,0.96))",
          border: `2px solid ${palette.red}88`,
          boxShadow: `0 0 34px ${palette.red}22`,
          padding: 22,
          boxSizing: "border-box",
          ...rise(frame, 76, 94),
        }}
      >
        <div style={{ color: palette.red, fontWeight: 900, fontSize: 28 }}>Human glue work</div>
        <div style={{ color: palette.muted, marginTop: 12, fontSize: 17, lineHeight: 1.35 }}>
          triage, context gathering, access chasing, copy/paste, handoffs, evidence writing
        </div>
        <div style={{ marginTop: 18, color: palette.amber, fontSize: 20, fontWeight: 850 }}>
          Backlog: {backlog} waiting
        </div>
      </div>

      {[
        ["ITSM", 1015, 185],
        ["IAM", 1185, 245],
        ["SIEM", 1032, 340],
        ["Email", 1190, 405],
        ["GitLab", 1035, 512],
        ["Docs", 1194, 575],
      ].map(([name, x, y], i) => (
        <Card key={name} x={Number(x)} y={Number(y)} w={220} h={76} label={String(name)} sub="separate login / context" delay={96 + i * 6} color={i % 2 ? palette.purple : palette.cyan} />
      ))}
      <Line x1={865} y1={386} x2={1015} y2={223} delay={130} color={palette.red} dashed />
      <Line x1={865} y1={386} x2={1185} y2={283} delay={136} color={palette.red} dashed />
      <Line x1={865} y1={386} x2={1032} y2={378} delay={142} color={palette.red} dashed />
      <Line x1={865} y1={386} x2={1190} y2={443} delay={148} color={palette.red} dashed />
      <Line x1={865} y1={386} x2={1035} y2={550} delay={154} color={palette.red} dashed />
      <Line x1={865} y1={386} x2={1194} y2={613} delay={160} color={palette.red} dashed />

      <Label x={1010} y={700} width={690} text="Automation often becomes another silo: more dashboards, more queues, more handoffs." size={30} color={palette.text} delay={182} />
      <Label x={1012} y={779} width={660} text="The work is still trapped between systems." size={24} color={palette.red} delay={205} />
    </Shell>
  );
};

const SolutionLayer: React.FC = () => {
  const frame = useCurrentFrame();
  const ring = interpolate(frame % 90, [0, 90], [0, 360]);
  return (
    <Shell title="The New Model: Governed Agent Work" kicker="Solution">
      <Label x={92} y={172} width={400} text="Any point of origin" size={26} color={palette.muted} delay={8} />
      {[
        ["Teams", 80, 240, "💬"],
        ["Email", 80, 345, "✉️"],
        ["Alert", 80, 450, "⚠️"],
        ["Ticket", 80, 555, "🎫"],
        ["CI/CD", 80, 660, "🚀"],
      ].map(([name, x, y, icon], i) => (
        <Card key={name} x={Number(x)} y={Number(y)} w={230} h={78} label={String(name)} icon={String(icon)} delay={18 + i * 7} color={i === 2 ? palette.amber : palette.cyan} />
      ))}
      {[279, 384, 489, 594, 699].map((y, i) => <Line key={y} x1={310} y1={y} x2={640} y2={440} delay={65 + i * 4} color={palette.cyan} />)}

      <div
        style={{
          position: "absolute",
          left: 625,
          top: 250,
          width: 550,
          height: 390,
          borderRadius: 26,
          background: "linear-gradient(180deg, rgba(84,214,255,0.14), rgba(14,27,45,0.98))",
          border: `2px solid ${palette.cyan}`,
          boxShadow: `0 0 48px ${palette.cyan}33`,
          padding: 28,
          boxSizing: "border-box",
          ...rise(frame, 78, 96),
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ color: palette.text, fontWeight: 900, fontSize: 31 }}>Agentic Ops Control Plane</div>
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: 999,
              border: `2px solid ${palette.green}`,
              transform: `rotate(${ring}deg)`,
              boxShadow: `0 0 25px ${palette.green}55`,
            }}
          />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 28 }}>
          {[
            ["Classify", palette.cyan],
            ["Route", palette.green],
            ["Assign Agent", palette.purple],
            ["Enforce Policy", palette.amber],
            ["Broker Access", palette.cyan],
            ["Record Evidence", palette.green],
          ].map(([text, color], i) => (
            <div
              key={text}
              style={{
                border: `1px solid ${color}88`,
                borderRadius: 10,
                padding: "12px 14px",
                color: color,
                fontWeight: 850,
                fontSize: 19,
                background: "rgba(7,17,31,0.52)",
                opacity: fade(frame, 98 + i * 5, 110 + i * 5),
              }}
            >
              {text}
            </div>
          ))}
        </div>
      </div>

      <Line x1={1175} y1={440} x2={1430} y2={300} delay={135} color={palette.green} />
      <Line x1={1175} y1={440} x2={1430} y2={430} delay={145} color={palette.green} />
      <Line x1={1175} y1={440} x2={1430} y2={560} delay={155} color={palette.green} />

      <Card x={1430} y={250} w={300} h={96} label="Scoped agents" sub="least privilege, task context" color={palette.green} delay={164} />
      <Card x={1430} y={382} w={300} h={96} label="Approval gates" sub="stop before risky actions" color={palette.amber} delay={174} />
      <Card x={1430} y={514} w={300} h={96} label="Tool adapters" sub="existing tools or reference modules" color={palette.purple} delay={184} />

      <Line x1={990} y1={640} x2={990} y2={775} delay={204} color={palette.cyan} />
      <Card x={770} y={770} w={440} h={92} label="Postmortem + learning loop" sub="successful work becomes workflow, skill, test, or automation" color={palette.green} delay={220} />
    </Shell>
  );
};

const ChatBubble: React.FC<{ x: number; y: number; w: number; text: string; who: "user" | "agent"; delay: number }> = ({
  x,
  y,
  w,
  text,
  who,
  delay,
}) => {
  const frame = useCurrentFrame();
  const color = who === "user" ? palette.cyan : palette.green;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        padding: "16px 18px",
        borderRadius: who === "user" ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
        border: `1px solid ${color}88`,
        background: who === "user" ? "rgba(84,214,255,0.13)" : "rgba(74,222,128,0.12)",
        color: palette.text,
        fontSize: 21,
        lineHeight: 1.25,
        boxShadow: `0 0 22px ${color}22`,
        ...rise(frame, delay, delay + 14),
      }}
    >
      {text}
    </div>
  );
};

const IntakeFlow: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Shell title="Intake Is Where It Clicks" kicker="Live story">
      <div
        style={{
          position: "absolute",
          left: 76,
          top: 166,
          width: 660,
          height: 770,
          borderRadius: 22,
          border: `1px solid ${palette.line}`,
          background: "rgba(10,20,34,0.88)",
          padding: 24,
          boxSizing: "border-box",
          ...rise(frame, 8, 24),
        }}
      >
        <div style={{ color: palette.text, fontSize: 26, fontWeight: 900 }}>Teams-style conversation</div>
        <div style={{ color: palette.muted, marginTop: 6, fontSize: 16 }}>The user describes the problem. The system creates work.</div>
        <ChatBubble x={118} y={275} w={530} who="user" delay={35} text="I can't log into my account and I have a customer call in 20 minutes." />
        <ChatBubble x={112} y={405} w={560} who="agent" delay={82} text="I can help. Is this your normal corporate account, and are you seeing password, MFA, or locked-account errors?" />
        <ChatBubble x={168} y={555} w={480} who="user" delay={135} text="It says my account is locked after too many attempts." />
        <ChatBubble x={112} y={660} w={560} who="agent" delay={184} text="I created an urgent access incident, routed it to IAM, and requested approval for unlock/reset." />
      </div>

      <Line x1={738} y1={550} x2={880} y2={550} delay={90} color={palette.cyan} />
      <div
        style={{
          position: "absolute",
          left: 875,
          top: 165,
          width: 900,
          height: 770,
          borderRadius: 22,
          border: `1px solid ${palette.line}`,
          background: "rgba(7,17,31,0.70)",
          padding: 26,
          boxSizing: "border-box",
        }}
      >
        <Label x={34} y={40} width={800} text="Behind the conversation" size={30} delay={100} />
        <Card x={45} y={120} w={330} h={92} label="Ticket created" sub="Incident • urgent • IAM route" color={palette.cyan} delay={118} />
        <Card x={465} y={120} w={330} h={92} label="Context checked" sub="related outages, policy, user identity" color={palette.purple} delay={142} />
        <Card x={45} y={270} w={330} h={92} label="Agent assigned" sub="scoped task context and permissions" color={palette.green} delay={168} />
        <Card x={465} y={270} w={330} h={92} label="Approval gate" sub="unlock/reset requires authorized approval" color={palette.amber} delay={198} />
        <Card x={45} y={420} w={330} h={92} label="Action completed" sub="approved account unlock/reset" color={palette.green} delay={232} />
        <Card x={465} y={420} w={330} h={92} label="Evidence written" sub="ticket note, audit trail, SLA metrics" color={palette.cyan} delay={258} />
        <Line x1={375} y1={166} x2={465} y2={166} delay={138} color={palette.cyan} />
        <Line x1={630} y1={212} x2={630} y2={270} delay={166} color={palette.cyan} />
        <Line x1={465} y1={316} x2={375} y2={316} delay={192} color={palette.cyan} />
        <Line x1={210} y1={362} x2={210} y2={420} delay={220} color={palette.cyan} />
        <Line x1={375} y1={466} x2={465} y2={466} delay={250} color={palette.green} />
        <Label x={60} y={570} width={770} text="The user sees a simple conversation. The business gets governed execution and audit evidence." size={28} color={palette.text} delay={282} />
      </div>
    </Shell>
  );
};

const AdoptionPath: React.FC = () => {
  const frame = useCurrentFrame();
  const steps = [
    ["Start small", "intake + tickets", palette.cyan],
    ["Add IAM", "access requests + approvals", palette.green],
    ["Add email", "phishing + quarantine", palette.amber],
    ["Add SIEM/EDR", "alerts + response", palette.red],
    ["Add CI/CD", "scan + remediate", palette.purple],
    ["Expand ops", "cloud, compliance, proactive work", palette.cyan],
  ];
  return (
    <Shell title="Adoption Is Modular, Not Big Bang" kicker="Deployment model">
      <Label x={96} y={166} width={860} text="The customer can deploy, integrate, or turn off each module." size={32} delay={14} />
      <Label x={97} y={270} width={920} text="That lets us land small, prove value, and expand as teams get comfortable." size={22} color={palette.muted} delay={28} />

      {steps.map(([name, sub, color], i) => {
        const x = 100 + i * 290;
        const y = 425 + Math.sin(i) * 18;
        return (
          <React.Fragment key={name}>
            <Card x={x} y={y} w={235} h={118} label={String(name)} sub={String(sub)} color={String(color)} delay={55 + i * 22} />
            {i < steps.length - 1 ? <Line x1={x + 235} y1={y + 59} x2={x + 290} y2={425 + Math.sin(i + 1) * 18 + 59} color={palette.cyan} delay={72 + i * 22} /> : null}
          </React.Fragment>
        );
      })}

      <div
        style={{
          position: "absolute",
          left: 250,
          top: 705,
          width: 1420,
          height: 148,
          borderRadius: 18,
          border: `1px solid ${palette.green}88`,
          background: "linear-gradient(90deg, rgba(74,222,128,0.11), rgba(84,214,255,0.09), rgba(167,139,250,0.10))",
          padding: 22,
          boxSizing: "border-box",
          opacity: fade(frame, 214, 236),
        }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20 }}>
          <div>
            <div style={{ color: palette.green, fontSize: 22, fontWeight: 900 }}>Use existing tools</div>
            <div style={{ color: palette.muted, fontSize: 17, marginTop: 7 }}>ServiceNow, Jira, Splunk, Sentinel, Okta, Entra, GitHub...</div>
          </div>
          <div>
            <div style={{ color: palette.cyan, fontSize: 22, fontWeight: 900 }}>Deploy reference modules</div>
            <div style={{ color: palette.muted, fontSize: 17, marginTop: 7 }}>iTop, Wazuh, Mailcow, GitLab, Keycloak, SearXNG...</div>
          </div>
          <div>
            <div style={{ color: palette.purple, fontSize: 22, fontWeight: 900 }}>Keep model routing private</div>
            <div style={{ color: palette.muted, fontSize: 17, marginTop: 7 }}>local/on-prem first, external only by policy</div>
          </div>
        </div>
      </div>
      <Label x={520} y={905} width={900} text="The same control plane grows into an agent-managed operations department." size={31} color={palette.text} delay={250} />
    </Shell>
  );
};

const Combo: React.FC = () => (
  <AbsoluteFill>
    <Sequence from={0} durationInFrames={12 * fps}>
      <ProblemState />
    </Sequence>
    <Sequence from={12 * fps} durationInFrames={12 * fps}>
      <SolutionLayer />
    </Sequence>
    <Sequence from={24 * fps} durationInFrames={13 * fps}>
      <IntakeFlow />
    </Sequence>
    <Sequence from={37 * fps} durationInFrames={12 * fps}>
      <AdoptionPath />
    </Sequence>
  </AbsoluteFill>
);

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="ProblemState" component={ProblemState} durationInFrames={12 * fps} fps={fps} width={1920} height={1080} />
    <Composition id="SolutionLayer" component={SolutionLayer} durationInFrames={12 * fps} fps={fps} width={1920} height={1080} />
    <Composition id="IntakeFlow" component={IntakeFlow} durationInFrames={13 * fps} fps={fps} width={1920} height={1080} />
    <Composition id="AdoptionPath" component={AdoptionPath} durationInFrames={12 * fps} fps={fps} width={1920} height={1080} />
    <Composition id="DemoV4Sequence" component={Combo} durationInFrames={49 * fps} fps={fps} width={1920} height={1080} />
  </>
);

registerRoot(RemotionRoot);

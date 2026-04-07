# Bridge Prompt Guide — Video Generation (Grok Imagine)

Each bridge = one generated video clip connecting two keyframe stills.

---

## ✅ Canonical Prompt Formula (LOCKED — validated 2026-04-07)

This is the formula that works. Use it as the base for every video prompt.

```
@image1 is the character reference for [CHARACTER]. This is a continuous [N]-second shot.
@image2 shows [CHARACTER] [START POSITION — describe what's happening].
[ACTION 1, verb + manner]. [ACTION 2, verb + manner] as shown in @image3.
[ACTION 3] as shown in @image4.
Smooth continuous camera follows [CAMERA MOVEMENT DESCRIPTION].
[LIGHTING]. No cuts.
```

**Rules locked in:**
1. Character ref is ALWAYS @image1
2. Scene keyframes reference in the order they appear (@image2, @image3, @image4...)
3. Write actions as continuous motion — no "then", no "next", no hard cuts
4. Door/object interactions: use "already open" — never animate a door opening
5. No glass/transparency language — say "doorway" not "glass door"
6. End with: "Smooth continuous camera follows [movement]. [Lighting]. No cuts."

**Validated example (The Midnight Builder — The Firing):**

> @image1 is the character reference for Marcus. This is a continuous 10-second shot. @image2 shows Marcus seated across from The Boss in the manager's office at the dark wood desk — The Boss has just placed a termination letter on the desk. Marcus grips the armrest, jaw tightening. He presses both palms flat on the desk as shown in @image3, rises slowly to standing with controlled dignity, back straight. He turns and walks deliberately toward the open doorway in the background. He steps through the already open doorway into the open-plan office as shown in @image4, the ACHIEVE poster on the wall behind him as he exits. Smooth continuous camera follows from medium, tilts up as he rises, then tracks behind him as he walks out. Cold fluorescent light throughout. No cuts.

**Results:** Zero ghosting. No door clipping. Character consistent throughout. ACHIEVE poster sharp and readable. Story arc reads in a single take.

---

---

## What a Bridge Is

```
KF-001 (still image)
    ↓
BR-001 (video clip — this is the bridge)
    ↓
KF-002 (still image)
    ↓
BR-002 (video clip)
    ↓
KF-003 (still image)
    ...
```

The stills are anchor frames. The bridges are the motion between them.

---

## The 4-Part Bridge Prompt Formula

Every bridge prompt must answer all 4:

```
1. CAMERA POSITION  — where is the camera in the scene?
2. CAMERA MOVEMENT  — does the camera move? how?
3. CHARACTER ACTION — what does the character do? (1-2 actions max)
4. ENVIRONMENT ANCHOR — what does the space look like? lighting?
```

### Template

```
[SHOT TYPE] shot, [CAMERA POSITION DESCRIPTION].
[CHARACTER] [ACTION VERB] [MANNER/PACE].
Camera [MOVEMENT OR "is static"].
[ENVIRONMENT DETAIL — key prop or light that anchors the scene].
```

---

## Shot Types & When to Use Them

| Shot Type | When to Use | Example |
|-----------|-------------|---------|
| **Over-the-shoulder (OTS)** | Conversations, reveals, confrontations | "OTS of Marcus — we see the letter sliding toward him" |
| **Low angle** | Character rising, gaining power, defiance | "Camera below desk, Marcus rises into frame" |
| **High angle** | Vulnerability, character feeling small | "Camera above, Marcus slumped in the chair" |
| **Tracking behind** | Character walking away, journey, exit | "Camera follows Marcus from behind toward the door" |
| **Tracking side** | Walking with purpose, lateral movement | "Camera tracks Marcus from the left as he crosses the office" |
| **Static medium** | Delivering information, tension holds | "Camera holds steady on both men across the desk" |
| **Slow push-in** | Building dread, revelation moment | "Camera slowly pushes toward Marcus's face" |
| **Pull-back reveal** | Showing scale, isolation | "Camera pulls back to reveal the empty office floor" |

---

## Camera Movement Vocabulary

Be specific. Vague = bad output.

| Term | What It Means |
|------|--------------|
| `camera is static` | No movement at all. Subject or props move. |
| `slow push-in` | Camera moves toward the subject slowly |
| `slow pull-back` | Camera moves away from the subject slowly |
| `slow tilt up` | Camera rotates upward on its axis (follows a rise) |
| `slow tilt down` | Camera rotates downward |
| `pan left / pan right` | Camera rotates horizontally, no position change |
| `tracking behind` | Camera follows subject from behind, moving forward |
| `tracking side` | Camera moves parallel to subject |
| `arc left / arc right` | Camera orbits around the subject |
| `handheld slight drift` | Subtle organic camera shake (tension, realism) |

---

## Action Rules

### 1-2 Actions Per Bridge

| Bridge Duration | Max Actions |
|-----------------|-------------|
| 2-3 seconds | 1 action |
| 4-5 seconds | 1-2 actions |
| 6-8 seconds | 2 actions |
| 9+ seconds | 2-3 actions (only if scene requires) |

### Good Action Language

Use: **verb + manner + pace**

- "slides a letter slowly across the desk" ✓
- "presses both palms flat on the desk and rises to standing deliberately" ✓  
- "turns from the desk and walks toward the door at a measured pace" ✓

Avoid:
- "does various things" ✗
- "reacts to the news" ✗ (too vague)
- "has a complex emotional moment" ✗ (unactionable)

---

## Environment Anchor

Always include 1-2 environment details so the model doesn't hallucinate a new set:

- Name the key prop: "the dark wood desk", "the glass door", "the 'ACHIEVE' poster"
- Name the lighting: "cold fluorescent light from above", "warm desk lamp from the right"
- Name what's blurred in background: "open-plan office blurred behind"

---

## Full Example — 3-Bridge Scene

**Scene:** Corporate firing. Marcus learns the news, rises, walks out.

### BR-001 — The Reveal (3s)
```
camera_position: Over-the-shoulder of Marcus (OTS), camera behind his right shoulder.
                 Marcus's jacket and ear in left foreground. The Boss faces the camera.
camera_movement: Static. Camera does not move.
prompt: "Over-the-shoulder shot behind Marcus's right shoulder. The Boss sits 
         across the dark wood desk facing the camera, slides a termination letter 
         slowly toward Marcus. Letter moves toward the camera. Camera is static. 
         Cold fluorescent light from above."
```

### BR-002 — The Rise (4s)
```
camera_position: Low angle, below desk height, looking up at Marcus.
camera_movement: Slow tilt up as Marcus rises — camera follows his head from 
                 desk level to standing height.
prompt: "Low angle shot below desk height looking up at Marcus. He presses 
         both palms flat on the dark wood desk and rises to standing 
         deliberately. Camera tilts upward slowly to follow him. Cold 
         fluorescent light from above."
```

### BR-003 — The Exit (6s)
```
camera_position: Tracking behind Marcus, shoulder height, 2 meters back.
camera_movement: Follows Marcus at steady pace. Holds as he pushes the door open.
prompt: "Tracking shot behind Marcus at shoulder height. He walks deliberately 
         toward the glass door. Camera follows from behind at a slow steady pace. 
         He reaches the door and pushes it open. Open-plan office comes into view 
         through the glass. Camera holds as the door swings. Cold fluorescent 
         light from above."
```

---

## Quick Reference Checklist

Before submitting a bridge prompt:

```
□ Camera position specified (OTS / low angle / tracking / etc.)
□ Camera movement specified (static / tilt / push / track / etc.)
□ 1-2 actions max (for the clip duration)
□ Actions use verb + manner + pace
□ Key prop named (anchor to the environment)
□ Lighting named
□ Duration matches action count (3s = 1 action, 4-6s = 2 actions)
```

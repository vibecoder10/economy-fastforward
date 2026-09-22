# DvsU — Producer File Standard
## The master reference document for each video

---

## WHAT THE PRODUCER FILE IS

The Producer File is the complete working document for one video. It contains all information needed to generate every visual and narration component of the video automatically — before publishing.

It is not the voiceover script. It is not a list of images. It is the master reference from which the voiceover script, images, on-screen text, and metadata are all derived.

**One Producer File = one complete video.**

---

## FILE STRUCTURE

The Producer File contains four blocks in strict order (on-screen text is not a separate block; it is generated from the data line in the Graphics List):

```
1. VIDEO TITLE
2. SCRIPT (with unit headers)
3. GRAPHICS LIST
4. THUMBNAIL
```

Nothing else. No notes, no comments, no production questions. If information is not in one of these four blocks — it does not belong in the Producer File.

---

## BLOCK 1: VIDEO TITLE

The published YouTube title. Centred, bold, large.

```
Every US Warship That Defined the Cold War
```

---

## BLOCK 2: SCRIPT

Every paragraph is preceded by a unit header in this exact format:

```
[NUMBER]  [FULL UNIT NAME]
[Role • Operator • Year(s)]
[paragraph text]
```

- Number and unit name: **bold**
- Data line (Role • Operator • Year): grey text
- Paragraph text: regular weight

**Example:**

```
15  USS Enterprise (CVN-65)
Nuclear carrier • US Navy • 1961–2012

When the Cuban Missile Crisis reached its peak in October 1962, USS Enterprise was 
already at sea in the Caribbean. Eight reactors gave her a speed of thirty-three 
knots and a range that required no logistical calculation...
```

### Data line format

The data line provides three pieces of information separated by bullets (•):

1. **Role** — one or two words describing what this machine was: *Attack carrier*, *Nuclear submarine*, *Heavy bomber*, *River gunboat*, *Strategic bomber*. Not a sentence. Not a description of significance. Just the function.
2. **Operator** — nation and service branch only. Never subdivisions, fleet numbers, or unit designations.
3. **Year(s)** — service period or the specific period relevant to this video

**Single-nation video:** Role • Operator • Year(s)
**Multi-nation video:** Role • Country/Operator • Year(s)

### Unit Identity Rule

**Every unit must be identified as a concrete individual machine — never as a class or type.**

Never display:
- Iowa-class battleship
- Tiger I
- Spitfire
- Destroyer

Always display:
- USS Iowa (BB-61)
- Tiger I Ausf. E
- Supermarine Spitfire Mk.IX
- USS The Sullivans (DD-537)

The audience must always know which exact machine is being discussed — not which family it belongs to.

### What is NOT in the script section:
- Act labels (ACT I, ACT II)
- B-roll cues or visual directions
- Pattern interrupt markers
- Thumbnail line
- Any text not meant to be spoken or displayed on screen

---

## BLOCK 3: GRAPHICS LIST

The Graphics List is the image brief for every unit. It mirrors the unit headers from Block 2 exactly — same order, same units.

**Format for each entry:**

```
[Full unit name]
[Role • Operator • Year(s)]
[Image brief — what the image must show, what it must not show]
```

Graphics entries must appear in **exactly the same order** as the spoken units in Block 2. Never reorder the Graphics List independently of the script.

Every graphics entry must correspond to exactly one script unit. No additional images that do not belong to a specific unit may appear in the Graphics List.

If the image generator is uncertain about the appearance of a machine — it must stop and regenerate, not guess. For military history content, a wrong image is worse than a missing one.

The image brief describes only what must be **visible in the image**. It never describes camera movement, animation, transitions, or editing. Those belong to Video Assembly.

The image brief tells the image generation system:
- Which machine to generate (exact variant)
- Which year/configuration to show
- Key visual features that must be correct
- Common errors to avoid for this specific vehicle

**Example:**

```
USS Enterprise CVN-65
Nuclear carrier • US Navy • 1961–2012

Show the distinctive eight-reactor hull configuration — no island stack, unique 
boxy superstructure with AN/SPS-32/33 fixed-array radars. 1962 Cuban Missile 
Crisis deployment configuration. DO NOT generate Nimitz-class — completely 
different superstructure.
```

**The Graphics List is the source document for:**
- Image generation prompts
- On-screen text (name + operator + year pulled from the data line)

---

## ON-SCREEN TEXT

Every unit in the video displays identifying text on screen. This text is automatically generated from the data line in the Graphics List.

**Text format:**
```
Line 1: [Full unit name]
Line 2: [Operator] • [Year(s)]
```

**Examples:**
```
USS Enterprise CVN-65
United States Navy • 1961–2012

Tiger I Ausf. E  
Wehrmacht • 1942–1944

Supermarine Spitfire Mk.IX
Royal Air Force • 1942–1954
```

The text appears with motion animation (fade in / slide) and disappears before the next unit begins. This is handled in video assembly — not in image generation. The image itself must be clean with no embedded text.

---

## BLOCK 4: THUMBNAIL

One line. Red, bold.

Format: `THUMBNAIL A/B TEST: [Unit A] / [Unit B]`

Only unit names. No descriptions.

**Example:**
```
THUMBNAIL A/B TEST: USS Nautilus / USS Arleigh Burke
```

The thumbnail uses one of the images already generated for the video — the image of Unit A for Thumbnail A, the image of Unit B for Thumbnail B. No separate image is generated for the thumbnail.

Text is added over the image in video/design assembly. The thumbnail text follows the Thumbnail Standard (separate document).

---

---

## COMPLETE EXAMPLE PRODUCER FILE

```
                    Every US Warship That Defined the Cold War


1  USS Missouri (BB-63)
Battleship • United States Navy • 1944–1992

On September 2, 1945, the war ended on her deck. The documents were signed in 
Tokyo Bay, General MacArthur presided, and the teak wood beneath his feet 
belonged to USS Missouri...

2  USS Forrestal (CVA-59)
Attack carrier • United States Navy • 1955–1993

The ship that obsoleted the battleship before the Cold War properly began was 
not an aircraft carrier. It was a nuclear bomb...

[...continues for all units...]


GRAPHICS LIST

USS Missouri (BB-63)
Iowa-class battleship • United States Navy • 1944–1992
Show Japanese surrender ceremony September 2, 1945 on teak deck in Tokyo Bay 
(NARA archival). Contrast with 1984 reactivation showing Tomahawk launchers. 
Same ship, two different worlds.

USS Forrestal (CVA-59)
Attack carrier • United States Navy • 1955–1993
Show at sea with Cold War-era jet aircraft on deck (F-8 Crusaders, A-4 Skyhawks). 
Show the 1,039-foot flight deck scale. First carrier built from keel up for 
nuclear strike mission.

[...continues for all units...]


THUMBNAIL A/B TEST: USS Nautilus / USS Arleigh Burke


```

---

## VERIFICATION BEFORE DELIVERY

Before the Producer File is used for production:

- [ ] All four blocks present in correct order
- [ ] Every unit in Block 2 has a matching entry in Block 3 (Graphics List)
- [ ] No duplicate units
- [ ] Data lines consistent between Block 2 and Block 3
- [ ] Thumbnail units exist in the video (their images will be used)
- [ ] No text that is not meant to be spoken or displayed on screen appears in Block 2


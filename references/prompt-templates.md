# Prompt templates

Use these internally. Do not expose them as instructions the user must paste.

These prompts apply to the regenerative branch. In faithful extraction, do not use image generation to create production RGB or alpha. A generated background-removal mask is diagnostic only and cannot subtract protected source pixels, determine bounds/pivot, or replace native source color.

Do not invoke the key-pose prompt once per timeline frame for a subtle idle. Approve a canonical master and only the minimum state variants or motion extrema that deterministic deformation cannot produce. Read [regenerative animation](regenerative-animation.md) before generating timeline assets.

## Canonical master

```text
Use case: canonical 2D game-animation master
Input: Image 1 is the authoritative character and neutral-pose reference.

Create one clean, high-resolution, complete full-body master sprite. Match the source character's identity, proportions, hairstyle, costume, colors, equipment, handedness, outlines, shading, camera, and style.

Composition: one character on a fixed square canvas with generous transparent padding. Keep all hair, clothing, weapons, equipment, and feet inside the canvas. Place both boot soles on one ground line around a bottom-center anatomical root.

Background: genuinely transparent RGBA with clean antialiased edges.

Frame contract: preserve the approved canvas, ground line, visible scale, bottom-center pivot, palette, outline thickness, camera, and locked regions exactly. Do not enlarge, recenter, crop, rescale, recolor, thicken outlines, redesign, or change equipment construction.

This frame is the immutable design authority for all later frames. Avoid background, grid, floor, shadow, text, extra views, cropping, automatic trimming, recentering, mirroring, redesign, extra limbs, equipment changes, perspective changes, and colored fringe.
```

## Key pose

```text
Use case: precise-object-edit
Asset type: one transparent frame in a 2D game animation

Inputs:
- Image 1: immutable canonical master and design authority.
- Image 2: source-video pose reference for this frame.
- Image 3, if supplied: previous approved key pose.

Frame: {frame_id}
Source timestamp: {timestamp}
Motion phase: {phase}
Motion progress: {progress}

Create exactly one controlled animation drawing. Reproduce the target motion from Image 2 while preserving Image 1's design.

Allowed changes: {moving_regions}
Locked regions: {locked_regions}
Geometric target: {pose_geometry}

Frame contract: canvas {canvas}; pivot {pivot}; ground line {ground_line}; visible scale {visible_scale}; locked-region tolerance {locked_tolerance}. Treat these as constraints, not suggestions.

Preserve character identity, proportions, limb lengths, costume, colors, materials, outlines, shading, camera, scale, handedness, canvas, and all unaffected regions. Keep stationary foot-contact points fixed. Do not align using silhouette bounds.

Output exactly one complete full-body sprite on a genuinely transparent canvas. No sheet, background, grid, shadow, text, crop, recentering, rescaling, redesign, extra limbs, or equipment drift.
```

## In-between

```text
Use case: precise-object-edit
Asset type: animation in-between

Inputs:
- Image 1: immutable canonical master.
- Image 2: approved starting pose.
- Image 3: approved ending pose.

Create one in-between at exactly {25|50|75}% progression from Image 2 to Image 3. Do not invent a third pose. Move each changing joint or object along the established arc, interpolate equipment orientation evenly, preserve limb lengths and volume, and preserve stationary regions exactly.

Allowed changes: {moving_regions}
Locked regions: {locked_regions}

Keep the shared canvas, camera, scale, ground line, and foot-contact behavior. Output one complete transparent full-body frame only. No sheet, background, crop, recentering, rescaling, redesign, or additional objects.
```

## Targeted retry

Repeat the original frame prompt and add only one correction:

```text
Correction: {single observed defect}. Change only what is necessary to fix it. Preserve the previously correct regions exactly.
```

Do not accumulate speculative negative instructions across retries.

## Discrete semantic state

```text
Use case: precise-object-edit
Asset type: one approved semantic layer for a 2D game animation

Image 1 is the immutable canonical master. Create only the {open-eyes|closed-eyes|mouth-state|hand-state} variant inside region {region}. Preserve every pixel outside that region exactly.

Keep the same canvas, pivot, scale, pose, palette, line weight, and transparency. Output the complete transparent frame for comparison plus the isolated transparent state layer. Do not redraw the head silhouette, hair, neck, collar, costume, or equipment.
```

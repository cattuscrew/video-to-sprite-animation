# Prompt templates

Use these internally for GPT Image. Do not ask the user to paste them.

## One-to-one source-frame edit

```text
Edit this exact source-video frame to remove only its background and return one complete transparent RGBA sprite.

This image is the mandatory pose authority for output frame {output_frame}, mapped from native frame {native_frame} at {timestamp}. Preserve its exact animation moment: silhouette, head and pelvis position, breathing phase, limb articulation, hair topology, eye state, overlaps, weapon and equipment angles, clothing, proportions, camera, and handedness.

Keep the entire character and both boots. Preserve the approved canvas, shared scale, bottom-center anatomical pivot, and ground line. Keep gaps under the chin, arms, hair, weapons, and equipment transparent.

Do not substitute another pose, neutralize the pose, use a canonical master as the pose source, warp a different frame, interpolate, mirror, crop, enlarge, recenter, redesign, recolor, or alter equipment.
```

If a secondary appearance reference is supplied, state explicitly that it may guide only cleanup/style fidelity and cannot override the mapped source frame’s pose or geometry.

## Targeted retry

Repeat the same mapped source-frame edit and add one correction:

```text
Correction: {single observed defect}. Repair only that defect while preserving the exact pose and all correct regions from native frame {native_frame}.
```

Do not retry from a prior failed output or a canonical master.

## Synthesized exception

Canonical-master generation, key-pose generation, and in-between prompts belong only to explicitly approved `frameConstruction: synthesized`. They must never be used in a one-to-one source-frame build.

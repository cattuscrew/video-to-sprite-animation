# Motion planning

## Plan in motion space

Equal timestamps do not imply equal visual spacing. Divide the source into phases and select frames by changes in pose, silhouette, expression, equipment angle, and motion direction.

For each planned pose, record:

- source timestamp
- phase and normalized progress
- key pose, in-between, or hold
- moving regions
- locked regions
- foot/root behavior
- facial state
- equipment orientation
- neighboring approved poses

## Starting thresholds

Add or request an in-between when an adjacent pair contains any of:

- more than roughly 15–20 degrees of equipment rotation
- more than 8–12 final pixels of landmark travel
- a direct transition between substantially different expressions
- a limb direction change without an intermediate arc
- an abrupt silhouette change

Treat these as starting points. Fast attacks may intentionally exceed them; restrained idles may require tighter spacing.

## Frame-count choice

- Subtle idle: commonly 12–20 unique drawings at 10–12 FPS.
- Expressive idle or equipment turn: commonly 18–28 unique drawings.
- Walk/run: choose poses from contact, down, passing, and up phases, then add in-betweens according to speed.
- Fast action: preserve anticipation, action, overshoot, and recovery rather than uniformly increasing frame count.

Choose the smallest set that preserves motion arcs. Holds and reverse playback may lengthen the timeline without adding unique drawings.

## Region locking

Define the minimum moving region for every phase. Examples:

- Blink: eyes only.
- Expression: eyes and mouth; preserve the head silhouette.
- Breathing: upper torso, shoulders, head, and limited secondary hair/cloth motion; keep feet planted.
- Shield turn: shield, gripping hand, and minimum necessary forearm; lock head, torso, legs, boots, sword arm, and sword.

If the image tool redraws locked regions, reject or repair the frame rather than accepting a visually attractive but temporally inconsistent result.

## Reversals

Reuse approved forward frames in reverse when the object or character truly retraces the same motion. Generate separate return frames only when the source has different follow-through, drag, overlap, or expression.


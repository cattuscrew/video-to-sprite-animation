# rembg extraction

Use this branch after the user confirms `rembg`. Frame construction remains independently set to `one-to-one-source`; every output uses its exact mapped native frame.

## Authority manifest

Record:

- `sourceKind`: `canonical-original` or `native-source-derived`
- `nativeSource`: the video or decoded native frames
- `frameConstruction`: `one-to-one-source`
- `pixelAuthority`: `native-source-rgb`
- `poseAuthority`: `selected-native-source-frame`
- `mappingRole`: `selected-source-frame-authority`
- `userApproved`: true only after the proof-frame gate
- `backgroundRemovalTool`: `rembg`
- `backgroundRemovalToolApproved`: true only after explicit user confirmation
- `processingMode`: `rembg-extraction`
- `derivedFromRejectedOutput`: false
- shared canvas, scale, integer translation, rembg model/configuration, and proof-frame identity

Validation must refuse a missing tool choice, unapproved tool, rejected authority, or circular reference.

## Safe extraction order

1. Decode the approved frames at native video resolution.
2. Run the approved rembg model at native resolution on each frame.
3. Treat rembg output as an alpha candidate only. Copy the original native RGB wherever alpha is visible; never use rembg-generated RGB, repainting, color-keying, flood-fill, OpenCV keying, or a custom fallback mask.
4. Keep every foreground component. Do not keep only the largest component and do not fill enclosed gaps automatically.
5. Apply the approved alpha to the untouched source RGB. Do not erode, dilate, feather, recolor, despill, or extend interior colors over the outline unless the user separately approves that operation.
6. Resize RGBA once with premultiplied-alpha resampling.
7. Apply one shared scale and integer translation. Do not independently recenter frames.

Use the installed rembg integration or connector available in the execution environment. If rembg is unavailable, stop and ask whether to use GPT Image. Switching tools does not change the selected frame mapping; GPT Image must edit every mapped frame individually.

## Proof-frame gate

Process exactly one representative frame with rembg. Render checkerboard, white, and black views plus 100%/4× crops of both under-chin regions, both armpits, hair/shoulder cavities, hands/weapons, equipment boundaries, and boots. Compare every visible pixel and silhouette against the exact native frame. Do not process the batch until the user approves the rembg proof and the manifest records that approval.

## Required rembg checks

- zero foreign visible RGB relative to the mapped native frame
- zero missing protected or dark-outline pixels after the approved alpha policy
- zero unexpected connected components
- zero new internal alpha holes in named negative spaces
- required fragile semantic regions present
- exact shared scale/translation and pivot behavior
- no per-frame rembg configuration changes
- complete output-to-native-frame/timestamp mapping
- full-batch alpha/topology contact sheet reviewed before packaging

High IoU, matching bounds, palette means, or edge density cannot waive missing parts or a visibly dirty matte.

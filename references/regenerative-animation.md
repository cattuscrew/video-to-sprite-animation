# Synthesized motion

Reaching this page does not mean the exception is available. It is open only when the user raised it themselves, unprompted, asking for frames that do not correspond one-to-one with the selected video frames. Never offer it, never list it beside `one-to-one-source` as a choice, and never propose it to rescue frames that keep failing. If the user has not raised it in their own words, close this page and stay one-to-one.

Examples include deforming one master from tracked centroids, landmarks, mesh, or optical flow; generating new poses; interpolation; or holding/reusing frames. Set `frameConstruction: synthesized`, build `motion-reference-manifest.json`, and classify every output as `source-derived-deformation`, `generated`, `interpolated`, or `held/reused`.

Never report synthesized outputs as the selected native video frames. Report native frame numbers only as motion references. If the user requires outputs to be the frames selected from the video, return to one-to-one processing and use each selected frame individually with the approved background tool.

Centroid-only and low-order curve motion are especially lossy: they discard articulation, rotation, overlap, silhouette, equipment angle, and topology. Do not use them without explicit approval and visible source-motion comparison.

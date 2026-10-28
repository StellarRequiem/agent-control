# Driving the mirrored iPhone

Apple's iPhone Mirroring window is a Continuity framebuffer. The desktop
leash can see the window and click it. Accessibility cannot see the phone UI.

Verified on this host with the app open:

| What the tools return | Value |
|---|---|
| `desktop.apps` process name | `iPhone Mirroring` |
| `desktop.windows` / `desktop.layout` title | `iPhone Mirroring` |
| Frame | valid bounds, top-left point space (not retina pixels) |
| `desktop.ax` after focus | one `AXGroup`, title `missing value`, value `missing value` |

`desktop.apps` does not return a bundle id. The published bundle id for this
app is `com.apple.ScreenContinuity`. Match the process name and window title
the tools return. Results include an `iphone_mirroring` block with those
patterns so a caller does not have to guess.

## See the phone

```text
desktop.screenshot_window  app="iPhone Mirroring"
```

The result keeps the private capture path and also includes:

- `data.image_png_base64` — raw standard base64 of the PNG (not a `data:` URL)
- `data.mime` — `image/png`
- `data.width`, `data.height` — PNG pixels, which may be retina-scaled versus the point frame
- `data.shared_path` — copy under `/Users/Shared/leash-captures/`, mode `0644`

`shell.read_file` decodes bytes as text and will not round-trip the PNG. Use
`image_png_base64` or the shared file. Prefer the window shot over a full
desktop screenshot.

A PNG over 8_000_000 raw bytes sets `data.image_omitted` to a short explanation
and leaves the file on disk. That cap is `MAX_INLINE_PNG_BYTES` from the
inline screenshot helper. The private capture's permissions are unchanged.

## Why AX is empty

That single `AXGroup` is the window. The mirrored display is not exposed as
buttons or text. `desktop.ax` does not add nodes. `desktop.ax_click` has
nothing to match inside the phone. The `iphone_mirroring.ax_note` on the AX
result says this in the tool response.

## Click and type

```text
desktop.layout
desktop.click_window  app="iPhone Mirroring"  rel_x=0.5  rel_y=0.4  focus=true
desktop.type          text="hello"
```

`rel_x` / `rel_y` are 0..1 inside the window. `local_x` / `local_y` are points
from the window origin. `focus` defaults to true and brings the window forward
before the click. A successful click reports `data.inside_window` when the
resolved point sits in that frame.

`desktop.type` and `desktop.press` go to the frontmost app, so focus the
mirroring window first. Return and Enter stay on the existing D4 confirm path.
Quit stays operator-confirmed, and this profile sets `allow_quit` false.

Nothing here adds iPhone Mirroring to an allowlist or removes anything from
the hard denylist. Password managers and MFA apps stay denied. Whether a click
is accepted is still the leash's current input scope (on this host,
operator-proxy allows a non-denylisted app).

## Do not

- Invent AX children for the phone screen.
- Read the PNG with `shell.read_file`.
- Guess full-screen coordinates. Take the frame from `desktop.layout`, then
  click inside it.

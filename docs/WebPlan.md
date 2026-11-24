# Web interface: plan

**Status:** agreed on 23 November 2026; steps 1 to 4 built on the `feat/web` branch (24 November 2026)
**Date:** 23 November 2026

## Goal

Let people use BatchSlicer from a browser: first on the computer it runs on,
and later from a phone, a laptop or a Windows or macOS computer on the same
network, while BatchSlicer runs on one Linux machine near the printer. Drop
models in, watch them slice, see the results with their preview pictures, and
get the G-code onto the printer.

It is the front end of what BatchSlicer already is with `--watch` and
`batchslicer service`: an appliance that turns models into G-code. It does
not replace the command line, and it does not try to be a slicer.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Separate project? | **No.** Same repository, optional extra: `pipx install "batchslicer[web]"`, then `batchslicer web` | It calls the same services as the command line; one set of tests, one release, nothing drifts. Users who only want the command line install nothing more. |
| Who slices? | **The watch folder**, not the web server | The web page puts uploads into a watched folder and shows what the watcher did. Slicing stays in the code that already works, runs, is tested and survives restarts. |
| One process or two? | **One process is the main way:** `batchslicer web --profile k2-pla` runs the page and one watcher together. With `batchslicer service` watchers installed, the page also offers each as a drop target | One process is easiest to start; services suit people who already run them, or one folder per printer. |
| Framework | **Starlette + Jinja2 templates, run by Uvicorn** | Small, well-maintained, handles large uploads by streaming; pages are made on the server, so no JavaScript build step. FastAPI would add Pydantic for little gain; Flask would need a separate server for production. |
| Live updates | **htmx** (one small JavaScript file shipped with the package), refreshing parts of the page every few seconds | Pages stay plain HTML; no front-end tool chain to maintain. |
| Who can open it? | **Only this computer in the first release.** Access from the local network (a phone, another computer), with a password, comes in a later release | It runs slicers and sends to printers, so it must not be open by accident; keeping the first release local leaves out the password and sign-in work until the pages are proven. |
| Platforms | Linux server; any browser | The slicers already run without a display (tested with all three on Linux and macOS; on Windows, Bambu Studio needs a signed-in desktop session), which a server needs. |

## What the first version does

It is opened in a browser on the computer BatchSlicer runs on.

1. **Upload.** Drag files or a whole folder onto the page. They are written to a hidden folder first and moved into the
   watched folder only when complete, so the watcher never sees half an
   upload. Only what the watcher slices is accepted (STL, 3MF and OBJ, and
   zip files of them; BatchSlicer does not take STEP), up to 2 GB at a
   time; names are cleaned so nothing lands outside the watched folder.
2. **Queue.** What is waiting in the watched folder, what is slicing now
   (model *n* of *m*), and what finished, newest first. Updated every few
   seconds.
3. **Results.** For each drop: the preview pictures (taken from the G-code's
   own picture blocks), print time, filament (per slot for multi-colour
   prints), filament changes, and each model's status, with the slicer's
   reason for a failure and BatchSlicer's hint. The report files can be
   downloaded.
4. **G-code.** Download one file, or a drop's files as a ZIP. Send them to a
   configured printer, keeping the folders, as `--send` does. Never start a
   print from the page in the first version.
5. **Printer.** Whether each configured printer answers, and for a Creality
   printer with a CFS, what is loaded in each slot, with colour swatches.
6. **About.** BatchSlicer's version, the profile each watcher uses, where the
   folders are, and the output of `batchslicer doctor` (useful for bug
   reports).

## What it does not do (first version)

- No editing of presets, profiles or the configuration; they stay in the
  slicers and in `profiles.yaml`.
- No 3D viewer and no arranging plates by hand.
- No starting, pausing or monitoring prints (Fluidd, Mainsail and the
  printer's screen do that).
- No access from other computers or phones (that comes later, with a
  password), and no user accounts.
- Not for the open internet, ever. For access from outside later, use a VPN
  such as Tailscale or WireGuard.

## How it fits the code

```
browser ──HTTP──▶ web/ (Starlette app, templates, static files)
                     │ reads and writes only inside the configured folders
                     ├─ upload ─────────▶ watched folder ──▶ watcher (services/watching.py)
                     ├─ queue, results ◀─ watch status file + output folders (report.json, G-code)
                     ├─ printers ──────▶ infrastructure/printer_clients.py (status, CFS, send)
                     └─ about ─────────▶ cli/doctor.py, installed services
```

- **New:** `web/` (app, routes, templates, static files), and a `batchslicer web`
  command in `cli/`.
- **One change to the watcher:** it writes a small status file
  (`.batchslicer-status.json`, hidden, in the watched folder) saying what it
  is slicing and how far it is, so the page can show progress. The watcher
  already ignores hidden files.
- **Reused as they are:** reports (`report.json`), preview pictures in the
  G-code, the printer clients, the sending service, `doctor`.
- **Shared helpers:** reading preview pictures out of G-code moves into
  `services/thumbnails.py`, next to the code that writes them.
- The `[web]` extra adds `starlette`, `uvicorn`, `jinja2` and
  `python-multipart`; htmx is shipped in the package, not downloaded.

## Security

- The first release listens only on `127.0.0.1` (this computer) and has no
  option to listen elsewhere.
- Every form carries a token and checks where the request came from, so
  another website open in the same browser cannot submit to it, and the page
  answers only to the host names `localhost` and `127.0.0.1` (against tricks
  that make a website look local).
- Network access, later: a password set with `batchslicer web
  --set-password`, stored hashed in the configuration; signing in sets a
  cookie that only this site can send (`SameSite=Strict`).
- Paths never come from the browser: uploads go into the watched folder,
  downloads come only from the output folder, and every path is checked to be
  inside them.
- Upload size and file types are limited; the page refuses to send to
  printers that are not in the configuration.
- `batchslicer service install --web` (later) runs the page as a user service,
  like the watcher.

## Testing

- Starlette's test client (adds `httpx` to the dev dependencies) for every
  page and action, against temporary folders, the stand-in slicer and the
  stand-in Moonraker and OctoPrint the tests already have.
- Security tests: a missing form token or a foreign origin is refused,
  requests for other host names are refused, `../` in upload names cannot
  escape, downloads outside the output folder are refused.
- A real run with the K2 Plus before release, in a browser on this computer.

## Steps

First release (this computer only):

| Step | What | Size |
|---|---|---|
| 1 | Status file from the watcher; `batchslicer web --profile ...` running the page and the watcher, with the queue and results pages (read-only) | Medium; **built** |
| 2 | Upload, and download (files and ZIP) | Medium; **built** |
| 3 | Printers page with the CFS, and sending from the page | Small-medium; **built** |
| 4 | About page; drop targets from installed watch services; `batchslicer service install --web` | Small; **built** |
| 5 | Docs, screenshots in the README, release | Small |

Step 1 alone already lets a watch run be followed in a browser on this
computer, so it can be released on its own.

Next release: access from the local network (a phone, another computer),
with a password.

## Later

- Access from the local network with a password (the release after the first).
- A Docker image with OrcaSlicer, so BatchSlicer runs on a NAS or home server
  without installing anything else (agreed for later, not now).
- Choosing a profile per upload, not only per watched folder.
- Starting a single-colour print from the page (behind a confirmation).
- Live progress through server-sent events instead of refreshing.

## Agreed with the project owner (23 November 2026)

1. The first version's scope is right: upload, queue, results, download,
   send, printers, about; no editing and no starting prints.
2. No phone or network access in the first release; this computer only.
3. One process (`batchslicer web --profile ...`) is the main way; services are
   the alternative.
4. A Docker image comes later.

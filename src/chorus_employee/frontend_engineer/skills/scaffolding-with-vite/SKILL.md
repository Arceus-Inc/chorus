---
name: scaffolding-with-vite
description: How to scaffold a framework app with Vite and keep it verifiable — creating the project non-interactively, wiring CI-safe test/build/preview scripts, and pointing Playwright's webServer at the preview build.
when_to_use: Read when you chose a framework (React, Vue, Svelte, Solid, …) and need a build tool. It sets the project up so `npm test` and `npx playwright test` both run green; for framework-specific footguns see the matching doctor skill.
---

# Scaffolding with Vite

Vite is the common, framework-agnostic build tool: it scaffolds React, Vue, Svelte, Solid, Lit, and
vanilla+TS projects from one command, gives you a dev server and a production build, and stays out of
the way. The job here is to scaffold **non-interactively** and wire the scripts the verifier re-runs.

## The one rule

**Scaffold the framework with Vite AT THE WORKTREE ROOT, then wire CI-safe `test` + `build` + `preview`
scripts and point Playwright's `webServer` at the preview — so a non-interactive re-run reaches green on
its own.**

## Put the project at the worktree ROOT (non-negotiable)

**Your worktree root IS the project root — `package.json` must sit at the TOP LEVEL of the worktree.**
The after-beat evidence floor and the re-run (`npm test`, `npx playwright test`) run from the worktree
root; a project inside a `my-app/` subfolder fails with "package.json not found" **even when the app is
perfect** — the single most common way a good build scores zero.

**⛔ Never run `npm create vite@latest .` (scaffold into the current directory).** The worktree root
already holds `.git` / `.harness`, so create-vite sees a non-empty directory and HANGS forever on a
"Current directory is not empty. Remove existing files and continue?" prompt a non-interactive beat can
never answer. A blocked/timed-out beat with no `package.json` is exactly this mistake.

### Do this — write the project files at the root yourself (deterministic, no prompt, no hoist)
A Vite app is a small, known set of files. Write them DIRECTLY at the worktree root with `write_file`:

- `package.json` — your stack's deps + the CI-safe scripts below.
- `index.html` — the Vite entry: a `<div id="root">` and `<script type="module" src="/src/main.tsx">`.
- `tsconfig.json` (+ `tsconfig.node.json`) and `vite.config.ts` (with `@vitejs/plugin-react` for React).
- `src/` — `main.tsx` (mounts the app onto `#root`), `App.tsx`, and your components.

Then `npm install` from the worktree root. This never hangs and needs no hoisting — prefer it.

### Only if you insist on the scaffolder: create a SUBFOLDER, then hoist to root
```bash
npm create vite@latest app -- --template react-ts   # a NAMED subfolder; --template avoids the prompt
# move EVERYTHING (incl. dotfiles) up to the worktree root, then delete the empty folder:
#   Windows (cmd.exe):  robocopy app . /E /MOVE   (robocopy exits 1 on SUCCESS — that is NOT an error)
#   POSIX:              (shopt -s dotglob; mv app/* . ) && rmdir app
```

**Confirm `package.json` is at the worktree root** (`dir package.json` / `ls package.json`) BEFORE you
write app code. Never `cd app` and build inside the subfolder.

## Meta-frameworks

- If the intent needs server-side rendering, routing, or SEO, a meta-framework (e.g. Next.js, Nuxt,
  SvelteKit) may fit better than a bare SPA — see `choosing-a-frontend-stack`. Those bring their own
  create-command and dev/build/preview scripts; the same CI-safe + Playwright wiring below applies.

## Wire CI-safe scripts

- Add a unit runner (`component-testing` covers Vitest + Testing Library) and wire it run-once:

  ```json
  {
    "scripts": {
      "dev": "vite",
      "build": "vite build",
      "preview": "vite preview",
      "test": "vitest run"
    }
  }
  ```

- `vitest run` (not bare `vitest`) exits instead of watching — a watch mode hangs the re-run. Setting
  `CI=1` also forces run-once for tools that honor it.
- `npm test` must map to your unit run so the captured `unit.txt` and the re-run line up.

## Point Playwright at the build

- Build then preview, and let Playwright start it (see `playwright-e2e-authoring`):

  ```js
  webServer: {
    // Bind 127.0.0.1 explicitly (a bare `npm run preview` can bind IPv6 `::1` and never answer a
    // 127.0.0.1 check → the webServer times out). `--strictPort` fails fast instead of drifting ports.
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,   // reuse a running server instead of colliding on the port on re-run
    timeout: 120_000,
  }
  ```

- Testing the preview (production) build catches build-time breakage the dev server would hide.

## Before you finish

1. Is `package.json` at the worktree ROOT (not inside a scaffolded subfolder)?
2. Did you scaffold non-interactively (`--template …`), so nothing waited on a prompt?
3. Is `npm test` wired to a run-once unit runner (no watch mode)?
4. Does Playwright's `webServer` build + serve the app, with ports in sync?
5. Do `npm test` and `npx playwright test` both reach green from a clean `npm install`?

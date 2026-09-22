// theme-literal-color-allowed: file — this is a standalone SSR-rendered
// fallback document (returned when the app's own server entry throws
// catastrophically), so it has no access to the React tree, app CSS bundle,
// or Electron's theme IPC. Like startup.html/repair.html it is themed via
// a `prefers-color-scheme` media query instead, matching styles.css's
// light/dark primitive values by hand since it cannot import that file.
export function renderErrorPage(): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Vault could not open this page</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="light dark" />
    <style>
      * { box-sizing: border-box; }
      body { font: 15px/1.5 system-ui, -apple-system, sans-serif; background: rgb(250 250 248); color: rgb(26 25 22); display: grid; place-items: center; min-height: 100vh; margin: 0; padding: 1.5rem; }
      main { max-width: 28rem; width: 100%; }
      .brand-logo { position: relative; display: block; width: 11.25rem; aspect-ratio: 260 / 118; overflow: hidden; user-select: none; }
      .brand-logo-art { position: absolute; inset: 0; background-image: url("/brand/Frame%208.png"); background-position: center; background-repeat: no-repeat; background-size: 320% auto; mix-blend-mode: multiply; }
      h1 { font-size: 1.5rem; letter-spacing: -0.02em; margin: 2.5rem 0 0.5rem; }
      p { color: rgb(94 91 84); margin: 0 0 1.75rem; }
      .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
      a, button { padding: 0.5rem 1rem; border-radius: 0.375rem; font: inherit; cursor: pointer; text-decoration: none; border: 1px solid transparent; }
      .primary { background: rgb(124 110 90); color: white; }
      .secondary { background: white; color: rgb(26 25 22); border-color: rgb(216 215 210); }
      @media (prefers-color-scheme: dark) {
        body { background: rgb(33 29 25); color: rgb(242 236 227); }
        .brand-logo-art { background-image: url("/brand/Frame%208%20inverted.svg?v=3"); mix-blend-mode: normal; }
        p { color: rgb(183 169 154); }
        .primary { background: rgb(201 169 125); color: rgb(33 29 25); }
        .secondary { background: rgb(44 38 33); color: rgb(242 236 227); border-color: rgb(78 67 57); }
      }
    </style>
  </head>
  <body>
    <main>
      <span class="brand-logo" role="img" aria-label="Vault"><span class="brand-logo-art" aria-hidden="true"></span></span>
      <h1>This page did not open</h1>
      <p>Try again. If it still does not open, return to Home.</p>
      <div class="actions">
        <button class="primary" onclick="location.reload()">Try again</button>
        <a class="secondary" href="/">Return home</a>
      </div>
    </main>
  </body>
</html>`;
}

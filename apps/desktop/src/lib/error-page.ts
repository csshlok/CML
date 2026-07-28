export function renderErrorPage(): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Vault could not open this page</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      * { box-sizing: border-box; }
      body { font: 15px/1.5 system-ui, -apple-system, sans-serif; background: rgb(250 250 248); color: rgb(26 25 22); display: grid; place-items: center; min-height: 100vh; margin: 0; padding: 1.5rem; }
      main { max-width: 28rem; width: 100%; }
      img { display: block; width: 11.25rem; height: auto; user-select: none; }
      h1 { font-size: 1.5rem; letter-spacing: -0.02em; margin: 2.5rem 0 0.5rem; }
      p { color: rgb(94 91 84); margin: 0 0 1.75rem; }
      .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
      a, button { padding: 0.5rem 1rem; border-radius: 0.375rem; font: inherit; cursor: pointer; text-decoration: none; border: 1px solid transparent; }
      .primary { background: rgb(124 110 90); color: white; }
      .secondary { background: white; color: rgb(26 25 22); border-color: rgb(216 215 210); }
    </style>
  </head>
  <body>
    <main>
      <img src="/brand/Container.svg" alt="Vault" draggable="false" />
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

// Arma la version web de Trappi Repartidor que sirve el servidor en trappi.com.ar/repartidor (para iPhone sin App Store:
// Safari -> Compartir -> Agregar a pantalla de inicio). Uso, desde driver/:  npm run export:web
// Deja todo en app/driver_web/ (se sube al repositorio y Render lo publica con el servidor).
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const here = path.dirname(new URL(import.meta.url).pathname);
const root = path.resolve(here, '..');
const out = path.resolve(root, '..', 'app', 'driver_web');
const base = '/repartidor';

fs.rmSync(out, { recursive: true, force: true });
execSync(`npx expo export -p web --output-dir "${out}" --clear`, { cwd: root, stdio: 'inherit', env: { ...process.env, EXPO_WEB_BASE: base } });

// icono para la pantalla de inicio del iPhone y manifiesto (nombre, colores, pantalla completa)
fs.copyFileSync(path.join(root, 'assets', 'icon.png'), path.join(out, 'icon.png'));
fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify({
  name: 'Trappi Repartidor', short_name: 'Repartidor', start_url: `${base}/`, scope: `${base}/`, display: 'standalone',
  background_color: '#000000', theme_color: '#000000', orientation: 'portrait',
  icons: [{ src: `${base}/icon.png`, sizes: '1024x1024', type: 'image/png', purpose: 'any maskable' }],
}, null, 2));
const head = [
  `<link rel="manifest" href="${base}/manifest.json"/>`,
  `<link rel="apple-touch-icon" href="${base}/icon.png"/>`,
  '<meta name="apple-mobile-web-app-capable" content="yes"/>',
  '<meta name="mobile-web-app-capable" content="yes"/>',
  '<meta name="apple-mobile-web-app-status-bar-style" content="black"/>',
  '<meta name="apple-mobile-web-app-title" content="Repartidor"/>',
  '<meta name="theme-color" content="#000000"/>',
].join('');
const indexPath = path.join(out, 'index.html');
let html = fs.readFileSync(indexPath, 'utf8')
  .replace('<html lang="en">', '<html lang="es">')
  .replace('initial-scale=1, shrink-to-fit=no', 'initial-scale=1, viewport-fit=cover, shrink-to-fit=no')
  .replace('<meta httpEquiv="X-UA-Compatible" content="IE=edge" />', '')
  .replace('</head>', `${head}</head>`)
  .replace('You need to enable JavaScript to run this app.', 'Para usar Trappi Repartidor activá JavaScript.');
fs.writeFileSync(indexPath, html);
fs.rmSync(path.join(out, 'metadata.json'), { force: true });
console.log(`Listo: ${path.relative(process.cwd(), out)}`);

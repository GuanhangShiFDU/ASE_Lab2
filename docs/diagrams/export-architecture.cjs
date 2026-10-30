// Run from any directory; install sharp in a separate tooling directory (see README).
const path = require('node:path');
const sharp = require('sharp');
const source = path.join(__dirname, 'architecture.svg');
const output = path.resolve(__dirname, '../../architecture.png');
sharp(source).png().toFile(output)
  .then(({ width, height }) => console.log(`Exported architecture.png (${width} x ${height})`))
  .catch(error => { console.error(error.message); process.exitCode = 1; });

const fs = require('fs');
const path = require('path');
const babel = require('./frontend/vendor/babel.min.js');
const input = path.join(__dirname,'frontend/assets/app.jsx');
const result = babel.transform(fs.readFileSync(input,'utf8'), {presets:[['react',{runtime:'classic'}]], filename:'app.jsx'});
fs.writeFileSync(path.join(__dirname,'frontend/assets/app.js'),result.code+'\n');
console.log('Compiled frontend/assets/app.js');
